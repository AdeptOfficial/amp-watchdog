"""Liveness ping: the SLP probe itself, and the AMP checker's override logic.

The probe tests run a real asyncio TCP server per scenario — the failure
mode this feature exists for (socket accepts, then silence) can't be
represented by a mock.
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from app.checkers import amp as amp_checker_module
from app.checkers.amp import AMPChecker
from app.clients.amp import AMPInstance
from app.core import mcping
from app.core.mcping import _varint, probe
from tests.test_scheduler import make_watch

# ---------- probe protocol ----------


@asynccontextmanager
async def _slp_server(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        # 3.12+: wait_closed() waits for handlers too — cap it so a
        # deliberately-stalling handler can't hang the suite
        try:
            await asyncio.wait_for(server.wait_closed(), timeout=3)
        except asyncio.TimeoutError:
            pass


async def test_probe_true_for_responding_server():
    payload = json.dumps({"version": {"name": "Paper"}, "players": {}}).encode()

    async def handler(reader, writer):
        await reader.read(64)  # handshake + status request
        body = _varint(0) + _varint(len(payload)) + payload
        writer.write(_varint(len(body)) + body)
        await writer.drain()
        writer.close()

    async with _slp_server(handler) as port:
        assert await probe("127.0.0.1", port, timeout=3) is True


async def test_probe_false_when_port_accepts_but_never_answers():
    """The wedged-sleep-listener shape: TCP connect succeeds, then nothing."""

    async def handler(reader, writer):
        await asyncio.sleep(1.5)  # outlives the probe timeout
        writer.close()

    async with _slp_server(handler) as port:
        assert await probe("127.0.0.1", port, timeout=0.5) is False


async def test_probe_false_on_connection_refused():
    async with _slp_server(lambda r, w: None) as port:
        pass  # server torn down; port is now closed
    assert await probe("127.0.0.1", port, timeout=2) is False


async def test_probe_false_on_garbage_response():
    async def handler(reader, writer):
        await reader.read(64)
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        writer.close()

    async with _slp_server(handler) as port:
        assert await probe("127.0.0.1", port, timeout=2) is False


# ---------- checker override logic ----------


class FakeAMPClientForChecker:
    def __init__(self, app_state=50):
        self.app_state = app_state

    async def get_instances(self):
        return [
            AMPInstance(
                instance_id="guid-lyd",
                instance_name="LOCKYOURDOOR01",
                friendly_name="LOCK YOUR DOOR",
                app_state=self.app_state,
                running=True,
                module="Minecraft",
            )
        ]


@pytest.fixture
def ping_watch():
    watch = make_watch(
        target_key="guid-lyd",
        display_name="LYD",
        config={"ping_host": "127.0.0.1", "ping_port": 31575},
    )
    watch.id = 1
    watch.ping_fail_count = 0
    return watch


@pytest.fixture
def checker(monkeypatch):
    client = FakeAMPClientForChecker()
    monkeypatch.setattr(amp_checker_module, "get_amp_client", lambda: client)
    checker = AMPChecker()
    checker._fake_client = client
    return checker


def _set_probe(monkeypatch, alive: bool):
    calls = []

    async def fake_probe(host, port, timeout=5.0):
        calls.append((host, port))
        return alive

    monkeypatch.setattr(mcping, "probe", fake_probe)
    return calls


async def test_ping_ok_keeps_amp_bucket(checker, ping_watch, monkeypatch):
    calls = _set_probe(monkeypatch, alive=True)
    results = await checker.check([ping_watch])
    assert calls == [("127.0.0.1", 31575)]
    assert results[1].bucket == "sleeping"
    assert results[1].error is None
    assert ping_watch.ping_fail_count == 0


async def test_first_ping_failure_warns_without_override(checker, ping_watch, monkeypatch):
    _set_probe(monkeypatch, alive=False)
    results = await checker.check([ping_watch])
    assert results[1].bucket == "sleeping"  # below threshold: no transition yet
    assert "1/2" in results[1].error
    assert ping_watch.ping_fail_count == 1


async def test_threshold_failures_override_to_offline(checker, ping_watch, monkeypatch):
    _set_probe(monkeypatch, alive=False)
    await checker.check([ping_watch])
    results = await checker.check([ping_watch])
    assert ping_watch.ping_fail_count == 2
    assert results[1].bucket == "offline"
    assert results[1].raw_state_name == "Sleeping (port dead)"
    assert "listener wedged" in results[1].error


async def test_recovery_resets_failure_streak(checker, ping_watch, monkeypatch):
    _set_probe(monkeypatch, alive=False)
    await checker.check([ping_watch])
    _set_probe(monkeypatch, alive=True)
    results = await checker.check([ping_watch])
    assert ping_watch.ping_fail_count == 0
    assert results[1].bucket == "sleeping"


async def test_no_ping_config_never_probes(checker, monkeypatch):
    watch = make_watch(target_key="guid-lyd", display_name="LYD", config={})
    watch.id = 1
    calls = _set_probe(monkeypatch, alive=False)
    results = await checker.check([watch])
    assert calls == []
    assert results[1].bucket == "sleeping"


async def test_amp_offline_skips_probe_and_wins(checker, ping_watch, monkeypatch):
    checker._fake_client.app_state = 0  # Stopped
    calls = _set_probe(monkeypatch, alive=True)
    results = await checker.check([ping_watch])
    assert calls == []  # offline per AMP needs no corroborating
    assert results[1].bucket == "offline"
    assert results[1].raw_state_name == "Stopped"


async def test_transitional_state_skips_probe(checker, ping_watch, monkeypatch):
    checker._fake_client.app_state = 10  # Starting
    calls = _set_probe(monkeypatch, alive=False)
    ping_watch.ping_fail_count = 1
    results = await checker.check([ping_watch])
    assert calls == []
    assert results[1].bucket == "transitional"
    assert ping_watch.ping_fail_count == 1  # streak preserved through the wake attempt

@pytest.mark.parametrize('body', [b'\x00\x00', b'\x00\x04oops', b'\x00\x02[]'])
async def test_probe_rejects_invalid_status_json(body):
    async def handler(reader, writer):
        await reader.read(512)
        writer.write(_varint(len(body)) + body)
        await writer.drain()
        writer.close()

    async with _slp_server(handler) as port:
        assert await probe('127.0.0.1', port, timeout=1) is False


async def test_probe_rejects_inconsistent_packet_length():
    async def handler(reader, writer):
        await reader.read(512)
        # Declared frame is too short to contain the advertised JSON string.
        writer.write(b'\x02\x00\x02{}')
        await writer.drain()
        writer.close()

    async with _slp_server(handler) as port:
        assert await probe('127.0.0.1', port, timeout=1) is False


async def test_liveness_persists_and_dispatches_offline_then_recovery(session_factory, checker, monkeypatch):
    from datetime import timedelta
    from sqlalchemy import select
    from app.models import Watch, Transition
    from app.services import scheduler as scheduler_module
    from tests.test_scheduler import NOW, _seed

    watch = make_watch(target_key='guid-lyd', display_name='test server',
                       config={'ping_host': '127.0.0.1', 'ping_port': 31575},
                       last_bucket='sleeping', last_app_state_name='Sleeping',
                       channel_ids=[1], mention_id='123', realert_minutes=0,
                       notify_rules={'sleeping->offline': True, 'offline->sleeping': True})
    [watch_id] = await _seed(session_factory, watch)
    monkeypatch.setattr(scheduler_module, 'get_checker', lambda _: checker)
    sent = []

    async def capture_dispatch(db, watch, message, kind):
        sent.append((message, kind))

    monkeypatch.setattr(scheduler_module, 'dispatch', capture_dispatch)
    _set_probe(monkeypatch, False)
    await scheduler_module.run_due_checks(session_factory, NOW)
    assert sent == []
    async with session_factory() as db:
        row = await db.get(Watch, watch_id)
        assert row.ping_fail_count == 1
        assert row.last_bucket == 'sleeping'
    await scheduler_module.run_due_checks(session_factory, NOW + timedelta(seconds=60))
    assert len(sent) == 1
    assert '<@123>' in sent[0][0] and 'port dead' in sent[0][0]
    # A continued outage must not create a duplicate transition alert.
    await scheduler_module.run_due_checks(session_factory, NOW + timedelta(seconds=120))
    assert len(sent) == 1
    _set_probe(monkeypatch, True)
    await scheduler_module.run_due_checks(session_factory, NOW + timedelta(seconds=180))
    assert len(sent) == 2 and '<@123>' not in sent[1][0]
    async with session_factory() as db:
        row = await db.get(Watch, watch_id)
        assert row.last_bucket == 'sleeping' and row.ping_fail_count == 0
        transitions = list((await db.execute(select(Transition).order_by(Transition.id))).scalars())
        assert [(t.from_bucket, t.to_bucket) for t in transitions] == [('sleeping', 'offline'), ('offline', 'sleeping')]
