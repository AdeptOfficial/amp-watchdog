from datetime import datetime

import httpx
from sqlalchemy import select

from app.core.notifier_base import NotifierPlugin, NotifyResult
from app.models import Channel, NotificationLog, Watch
from app.notifiers.discord import DISCORD_MAX, DiscordNotifier
from app.services import notify as notify_module
from app.services.notify import dispatch, render_message

NOW = datetime(2026, 10, 17, 12, 0, 0)


class CapturingTransportNotifier(DiscordNotifier):
    """DiscordNotifier with its HTTP call captured via monkeypatched client."""


async def test_discord_sends_content_payload(monkeypatch):
    captured = {}

    class StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.notifiers.discord.httpx.AsyncClient", StubClient)
    plugin = DiscordNotifier()
    result = await plugin.send(
        {"webhook_url": "https://discord.com/api/webhooks/1/token"}, "hello"
    )
    assert result.success is True
    assert captured["json"] == {"content": "hello"}


async def test_discord_truncates_long_messages(monkeypatch):
    captured = {}

    class StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            captured["json"] = json
            return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.notifiers.discord.httpx.AsyncClient", StubClient)
    plugin = DiscordNotifier()
    await plugin.send({"webhook_url": "https://discord.com/api/webhooks/1/t"}, "x" * 3000)
    assert len(captured["json"]["content"]) <= DISCORD_MAX


def test_discord_validate_config():
    plugin = DiscordNotifier()
    assert plugin.validate_config({}) != []
    assert plugin.validate_config({"webhook_url": "http://evil.example"}) != []
    assert plugin.validate_config({"webhook_url": "https://discord.com/api/webhooks/1/t"}) == []


def make_watch(**overrides) -> Watch:
    watch = Watch(
        type="amp", target_key="k", display_name="LYD",
        config={"instance_name": "LOCKYOURDOOR01"},
        last_app_state_name="Stopped", mention_id=None, message_template=None,
        channel_ids=[],
    )
    for key, value in overrides.items():
        setattr(watch, key, value)
    return watch


def test_render_default_template():
    watch = make_watch(mention_id="42")
    message = render_message(watch, "transition", "online", "offline", "UTC", NOW)
    assert "<@42>" in message
    assert "**LYD**" in message
    assert "offline" in message
    assert "Stopped" in message


def test_render_custom_template_with_unknown_placeholder():
    watch = make_watch(message_template="{name} went {to_state} at {time} {bogus}")
    message = render_message(watch, "transition", "online", "offline", "UTC", NOW)
    assert message == "LYD went offline at 12:00 {bogus}"


def test_render_realert_prefix():
    watch = make_watch()
    message = render_message(watch, "realert", "offline", "offline", "UTC", NOW)
    assert message.startswith("⏰ (still)")


class FakeNotifier(NotifierPlugin):
    type = "fake"
    display_name = "Fake"

    def __init__(self, success=True):
        self.sent: list[str] = []
        self.success = success

    async def send(self, config, message):
        self.sent.append(message)
        return NotifyResult(success=self.success, error=None if self.success else "boom")


async def test_dispatch_logs_per_channel_and_skips_disabled(db_session, monkeypatch):
    enabled = Channel(name="a", type="fake", config={}, enabled=True)
    disabled = Channel(name="b", type="fake", config={}, enabled=False)
    db_session.add_all([enabled, disabled])
    watch = make_watch()
    db_session.add(watch)
    await db_session.commit()

    fake = FakeNotifier()
    monkeypatch.setattr(notify_module, "get_notifier", lambda t: fake)

    watch.channel_ids = [enabled.id, disabled.id, 9999]  # 9999 = dangling
    await dispatch(db_session, watch, "msg", "transition")
    await db_session.commit()

    assert fake.sent == ["msg"]  # only the enabled channel
    logs = list((await db_session.execute(select(NotificationLog))).scalars())
    assert len(logs) == 1
    assert logs[0].success is True
    assert logs[0].channel_id == enabled.id


async def test_dispatch_logs_failures(db_session, monkeypatch):
    channel = Channel(name="c", type="fake", config={}, enabled=True)
    watch = make_watch()
    db_session.add_all([channel, watch])
    await db_session.commit()

    fake = FakeNotifier(success=False)
    monkeypatch.setattr(notify_module, "get_notifier", lambda t: fake)

    watch.channel_ids = [channel.id]
    await dispatch(db_session, watch, "msg", "transition")
    await db_session.commit()

    logs = list((await db_session.execute(select(NotificationLog))).scalars())
    assert len(logs) == 1
    assert logs[0].success is False
    assert logs[0].error == "boom"
