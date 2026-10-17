import httpx
import pytest_asyncio
from sqlalchemy import select

from app.core.notifier_base import NotifierPlugin, NotifyResult
from app.database import get_db
from app.main import app
from app.models import Channel, NotificationLog, Transition, Watch
from app.notifiers import load_notifiers


@pytest_asyncio.fixture
async def client(session_factory):
    load_notifiers()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_watch_and_rows(client, session_factory):
    resp = await client.post("/api/watches", data={
        "target_key": "lyd-guid", "name": "LOCK YOUR DOOR", "instance_name": "LOCKYOURDOOR01",
    })
    assert resp.status_code == 200
    assert "refresh-watches" in resp.headers.get("HX-Trigger", "")

    # duplicate target_key is a no-op, not an error
    resp2 = await client.post("/api/watches", data={
        "target_key": "lyd-guid", "name": "dupe", "instance_name": "x",
    })
    assert resp2.status_code == 200
    async with session_factory() as db:
        watches = list((await db.execute(select(Watch))).scalars())
        assert len(watches) == 1
        assert watches[0].notify_rules["online->offline"] is True


async def test_update_watch_rules_and_channels(client, session_factory):
    async with session_factory() as db:
        watch = Watch(type="amp", target_key="g1", display_name="W", config={},
                      channel_ids=[], notify_rules={})
        channel = Channel(name="chan", type="discord",
                          config={"webhook_url": "https://discord.com/api/webhooks/1/t"})
        db.add_all([watch, channel])
        await db.commit()
        watch_id, channel_id = watch.id, channel.id

    resp = await client.post(f"/api/watches/{watch_id}", data={
        "display_name": "Renamed",
        "check_interval_seconds": "120",
        "realert_minutes": "30",
        "mention_id": "42",
        "quiet_start": "22:00",
        "quiet_end": "07:00",
        "rule__online->offline": "on",
        "rule__offline->online": "on",
        "channels": str(channel_id),
        "message_template": "",
    })
    assert resp.status_code == 200
    async with session_factory() as db:
        refreshed = await db.get(Watch, watch_id)
        assert refreshed.display_name == "Renamed"
        assert refreshed.check_interval_seconds == 120
        assert refreshed.realert_minutes == 30
        assert refreshed.mention_id == "42"
        assert refreshed.quiet_start == "22:00"
        assert refreshed.notify_rules["online->offline"] is True
        assert refreshed.notify_rules["online->sleeping"] is False
        assert refreshed.channel_ids == [channel_id]
        assert refreshed.message_template is None


async def test_delete_watch_removes_history(client, session_factory):
    async with session_factory() as db:
        watch = Watch(type="amp", target_key="g2", display_name="D", config={}, channel_ids=[])
        db.add(watch)
        await db.commit()
        db.add(Transition(watch_id=watch.id, from_bucket="online", to_bucket="offline"))
        await db.commit()
        watch_id = watch.id

    resp = await client.delete(f"/api/watches/{watch_id}")
    assert resp.status_code == 200
    async with session_factory() as db:
        assert await db.get(Watch, watch_id) is None
        transitions = list((await db.execute(select(Transition))).scalars())
        assert transitions == []


async def test_check_now_queues(client, session_factory):
    async with session_factory() as db:
        watch = Watch(type="amp", target_key="g3", display_name="C", config={}, channel_ids=[])
        db.add(watch)
        await db.commit()
        watch_id = watch.id

    resp = await client.post(f"/api/watches/{watch_id}/check-now")
    assert resp.status_code == 200
    async with session_factory() as db:
        refreshed = await db.get(Watch, watch_id)
        assert refreshed.next_check_at is not None


async def test_create_channel_validation(client):
    resp = await client.post("/api/channels", data={
        "name": "", "type": "discord", "config_webhook_url": "nope",
    })
    assert resp.status_code == 200
    assert "Name is required" in resp.text
    assert "Webhook URL" in resp.text


async def test_create_and_test_channel(client, session_factory, monkeypatch):
    resp = await client.post("/api/channels", data={
        "name": "alerts", "type": "discord",
        "config_webhook_url": "https://discord.com/api/webhooks/1/t",
    })
    assert resp.status_code == 200
    assert "alerts" in resp.text

    class FakeNotifier(NotifierPlugin):
        type = "discord"
        display_name = "Fake"

        async def send(self, config, message):
            return NotifyResult(success=True)

    monkeypatch.setattr("app.routers.api.get_notifier", lambda t: FakeNotifier())

    async with session_factory() as db:
        channel = (await db.execute(select(Channel))).scalars().first()
        channel_id = channel.id

    resp2 = await client.post(f"/api/channels/{channel_id}/test")
    assert resp2.status_code == 200
    async with session_factory() as db:
        refreshed = await db.get(Channel, channel_id)
        assert refreshed.last_test_ok is True
        logs = list((await db.execute(select(NotificationLog))).scalars())
        assert len(logs) == 1
        assert logs[0].kind == "test"


async def test_edit_channel_updates_config_and_test_message(client, session_factory):
    async with session_factory() as db:
        channel = Channel(name="orig", type="discord",
                          config={"webhook_url": "https://discord.com/api/webhooks/1/old"})
        db.add(channel)
        await db.commit()
        channel_id = channel.id

    resp = await client.post(f"/api/channels/{channel_id}", data={
        "name": "renamed",
        "config_webhook_url": "https://discord.com/api/webhooks/2/new",
        "test_message": "custom test ping",
    })
    assert resp.status_code == 200
    async with session_factory() as db:
        refreshed = await db.get(Channel, channel_id)
        assert refreshed.name == "renamed"
        assert refreshed.config["webhook_url"] == "https://discord.com/api/webhooks/2/new"
        assert refreshed.test_message == "custom test ping"

    # invalid webhook is rejected and nothing changes
    resp2 = await client.post(f"/api/channels/{channel_id}", data={
        "name": "renamed", "config_webhook_url": "http://evil.example", "test_message": "",
    })
    assert "Webhook URL" in resp2.text
    async with session_factory() as db:
        refreshed = await db.get(Channel, channel_id)
        assert refreshed.config["webhook_url"] == "https://discord.com/api/webhooks/2/new"


async def test_channel_test_uses_custom_message(client, session_factory, monkeypatch):
    async with session_factory() as db:
        channel = Channel(name="t", type="discord",
                          config={"webhook_url": "https://discord.com/api/webhooks/1/t"},
                          test_message="my custom test")
        db.add(channel)
        await db.commit()
        channel_id = channel.id

    sent = []

    class FakeNotifier(NotifierPlugin):
        type = "discord"
        display_name = "Fake"

        async def send(self, config, message):
            sent.append(message)
            return NotifyResult(success=True)

    monkeypatch.setattr("app.routers.api.get_notifier", lambda t: FakeNotifier())
    resp = await client.post(f"/api/channels/{channel_id}/test")
    assert resp.status_code == 200
    assert sent == ["my custom test"]


async def test_delete_channel_scrubs_watch_refs(client, session_factory):
    async with session_factory() as db:
        channel = Channel(name="gone", type="discord", config={})
        db.add(channel)
        await db.commit()
        watch = Watch(type="amp", target_key="g4", display_name="S", config={},
                      channel_ids=[channel.id])
        db.add(watch)
        await db.commit()
        channel_id, watch_id = channel.id, watch.id

    resp = await client.delete(f"/api/channels/{channel_id}")
    assert resp.status_code == 200
    async with session_factory() as db:
        refreshed = await db.get(Watch, watch_id)
        assert refreshed.channel_ids == []


async def test_pages_render(client):
    for path in ("/", "/watches", "/channels"):
        resp = await client.get(path)
        assert resp.status_code == 200
        assert "amp-watchdog" in resp.text
