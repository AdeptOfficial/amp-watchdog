from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.checker_base import CheckerPlugin, CheckResult
from app.models import Transition, Watch, default_notify_rules
from app.services import scheduler as scheduler_module
from app.services.scheduler import run_due_checks

NOW = datetime(2026, 10, 17, 12, 0, 0)


class StubChecker(CheckerPlugin):
    type = "amp"
    display_name = "stub"

    def __init__(self, result_bucket="sleeping", raw_state=50, raw_state_name="Sleeping", error=None):
        self.calls: list[list[int]] = []
        self.result = CheckResult(bucket=result_bucket, raw_state=raw_state, raw_state_name=raw_state_name)
        self.raise_error = error

    async def check(self, watches):
        self.calls.append([w.id for w in watches])
        if self.raise_error:
            raise self.raise_error
        return {w.id: self.result for w in watches}


def make_watch(**overrides) -> Watch:
    defaults = dict(
        type="amp",
        target_key=f"guid-{overrides.get('display_name', 'x')}",
        display_name="w",
        config={},
        enabled=True,
        check_interval_seconds=60,
        notify_rules=default_notify_rules(),
        channel_ids=[],
        last_bucket="unknown",
        consecutive_errors=0,
    )
    defaults.update(overrides)
    return Watch(**defaults)


async def _seed(session_factory, *watches):
    async with session_factory() as db:
        for w in watches:
            db.add(w)
        await db.commit()
        return [w.id for w in watches]


async def test_only_due_watches_checked(session_factory, monkeypatch):
    due = make_watch(display_name="due", next_check_at=NOW - timedelta(seconds=1))
    future = make_watch(display_name="future", target_key="guid-f", next_check_at=NOW + timedelta(hours=1))
    never_checked = make_watch(display_name="fresh", target_key="guid-n", next_check_at=None)
    disabled = make_watch(display_name="off", target_key="guid-d", enabled=False, next_check_at=None)
    ids = await _seed(session_factory, due, future, never_checked, disabled)

    stub = StubChecker()
    monkeypatch.setattr(scheduler_module, "get_checker", lambda t: stub)

    checked = await run_due_checks(session_factory=session_factory, now=NOW)
    assert set(checked) == {ids[0], ids[2]}  # due + never-checked; not future, not disabled
    assert len(stub.calls) == 1  # one batched call


async def test_batch_one_backend_call_for_many_watches(session_factory, monkeypatch):
    watches = [make_watch(display_name=f"w{i}", target_key=f"guid-{i}") for i in range(3)]
    await _seed(session_factory, *watches)
    stub = StubChecker()
    monkeypatch.setattr(scheduler_module, "get_checker", lambda t: stub)

    await run_due_checks(session_factory=session_factory, now=NOW)
    assert len(stub.calls) == 1
    assert len(stub.calls[0]) == 3


async def test_next_check_at_advances_per_watch_interval(session_factory, monkeypatch):
    watch = make_watch(check_interval_seconds=300)
    ids = await _seed(session_factory, watch)
    stub = StubChecker()
    monkeypatch.setattr(scheduler_module, "get_checker", lambda t: stub)

    await run_due_checks(session_factory=session_factory, now=NOW)
    async with session_factory() as db:
        refreshed = await db.get(Watch, ids[0])
        assert refreshed.next_check_at == NOW + timedelta(seconds=300)
        assert refreshed.last_bucket == "sleeping"

    # Transition from unknown -> sleeping recorded (suppressed, no rule)
    async with session_factory() as db:
        transitions = list((await db.execute(select(Transition))).scalars())
        assert len(transitions) == 1
        assert transitions[0].from_bucket == "unknown"
        assert transitions[0].to_bucket == "sleeping"
        assert transitions[0].notified is False


async def test_checker_failure_records_errors_without_transitions(session_factory, monkeypatch):
    watch = make_watch(last_bucket="online")
    ids = await _seed(session_factory, watch)
    stub = StubChecker(error=ConnectionError("AMP unreachable"))
    monkeypatch.setattr(scheduler_module, "get_checker", lambda t: stub)

    await run_due_checks(session_factory=session_factory, now=NOW)
    async with session_factory() as db:
        refreshed = await db.get(Watch, ids[0])
        assert refreshed.consecutive_errors == 1
        assert "AMP unreachable" in refreshed.last_error
        assert refreshed.last_bucket == "online"  # no fabricated offline
        assert refreshed.next_check_at == NOW + timedelta(seconds=60)
        transitions = list((await db.execute(select(Transition))).scalars())
        assert transitions == []


async def test_missing_checker_type_is_an_error_not_a_crash(session_factory, monkeypatch):
    watch = make_watch()
    ids = await _seed(session_factory, watch)
    monkeypatch.setattr(scheduler_module, "get_checker", lambda t: None)

    await run_due_checks(session_factory=session_factory, now=NOW)
    async with session_factory() as db:
        refreshed = await db.get(Watch, ids[0])
        assert refreshed.consecutive_errors == 1
        assert "no checker" in refreshed.last_error
