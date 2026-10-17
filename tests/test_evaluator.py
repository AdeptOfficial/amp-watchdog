from datetime import datetime, timedelta

from app.core.checker_base import CheckResult
from app.models import Watch, default_notify_rules
from app.services.evaluator import evaluate, in_quiet_hours

NOW = datetime(2026, 10, 17, 12, 0, 0)  # naive UTC
TZ = "UTC"  # tests pin TZ=UTC so local == UTC


def make_watch(**overrides) -> Watch:
    watch = Watch(
        type="amp",
        target_key="lyd-guid",
        display_name="LYD",
        config={"instance_name": "LOCKYOURDOOR01"},
        enabled=True,
        check_interval_seconds=60,
        notify_rules=default_notify_rules(),
        channel_ids=[1],
        realert_minutes=0,
        last_bucket="online",
        last_app_state=20,
        last_app_state_name="Ready",
        consecutive_errors=0,
    )
    for key, value in overrides.items():
        setattr(watch, key, value)
    return watch


def offline_result():
    return CheckResult(bucket="offline", raw_state=0, raw_state_name="Stopped")


def test_stable_transition_notifies_when_rule_on():
    watch = make_watch()
    outcome = evaluate(watch, offline_result(), NOW, TZ)
    assert outcome.notify_kind == "transition"
    assert outcome.transition["from_bucket"] == "online"
    assert outcome.transition["to_bucket"] == "offline"
    assert outcome.transition["notified"] is True
    assert watch.last_bucket == "offline"
    assert watch.last_change_at == NOW
    assert watch.last_notified_at == NOW


def test_rule_off_suppresses_but_records():
    watch = make_watch(notify_rules={"online->offline": False})
    outcome = evaluate(watch, offline_result(), NOW, TZ)
    assert outcome.notify_kind is None
    assert outcome.transition["suppress_reason"] == "rule_off"
    assert watch.last_bucket == "offline"  # state still tracked


def test_no_channels_suppresses():
    watch = make_watch(channel_ids=[])
    outcome = evaluate(watch, offline_result(), NOW, TZ)
    assert outcome.notify_kind is None
    assert outcome.transition["suppress_reason"] == "no_channels"


def test_quiet_hours_suppresses():
    watch = make_watch(quiet_start="11:00", quiet_end="13:00")  # NOW is 12:00 UTC
    outcome = evaluate(watch, offline_result(), NOW, TZ)
    assert outcome.notify_kind is None
    assert outcome.transition["suppress_reason"] == "quiet_hours"


def test_transitional_never_alerts_or_clobbers_bucket():
    watch = make_watch()
    outcome = evaluate(
        watch, CheckResult(bucket="transitional", raw_state=30, raw_state_name="Restarting"), NOW, TZ
    )
    assert outcome.transition is None
    assert outcome.notify_kind is None
    assert watch.last_bucket == "online"  # unchanged
    assert watch.last_app_state_name == "Restarting"  # display updated

    # Restart completes: online again -> no transition (same stable bucket)
    outcome2 = evaluate(
        watch, CheckResult(bucket="online", raw_state=20, raw_state_name="Ready"), NOW, TZ
    )
    assert outcome2.transition is None
    assert outcome2.notify_kind is None


def test_first_observation_records_but_never_notifies():
    watch = make_watch(last_bucket="unknown", last_app_state=None, last_app_state_name=None)
    outcome = evaluate(
        watch, CheckResult(bucket="sleeping", raw_state=50, raw_state_name="Sleeping"), NOW, TZ
    )
    assert outcome.transition["from_bucket"] == "unknown"
    assert outcome.transition["suppress_reason"] == "rule_off"  # no unknown-> rules exist
    assert outcome.notify_kind is None
    assert watch.last_bucket == "sleeping"


def test_realert_fires_after_cooldown():
    watch = make_watch(
        last_bucket="offline",
        realert_minutes=60,
        last_notified_at=NOW - timedelta(minutes=61),
    )
    outcome = evaluate(watch, offline_result(), NOW, TZ)
    assert outcome.notify_kind == "realert"
    assert outcome.transition is None
    assert watch.last_notified_at == NOW


def test_realert_respects_cooldown_and_zero_setting():
    watch = make_watch(
        last_bucket="offline", realert_minutes=60, last_notified_at=NOW - timedelta(minutes=30)
    )
    assert evaluate(watch, offline_result(), NOW, TZ).notify_kind is None

    watch2 = make_watch(
        last_bucket="offline", realert_minutes=0, last_notified_at=NOW - timedelta(days=1)
    )
    assert evaluate(watch2, offline_result(), NOW, TZ).notify_kind is None


def test_realert_suppressed_during_quiet_hours():
    watch = make_watch(
        last_bucket="offline",
        realert_minutes=60,
        last_notified_at=NOW - timedelta(hours=2),
        quiet_start="11:00",
        quiet_end="13:00",
    )
    assert evaluate(watch, offline_result(), NOW, TZ).notify_kind is None


def test_error_counting_resets_on_success():
    watch = make_watch()
    evaluate(watch, CheckResult(bucket="unknown", raw_state_name="NotVisible", error="boom"), NOW, TZ)
    assert watch.consecutive_errors == 1
    assert watch.last_error == "boom"
    evaluate(watch, CheckResult(bucket="online", raw_state=20, raw_state_name="Ready"), NOW, TZ)
    assert watch.consecutive_errors == 0
    assert watch.last_error is None


def test_quiet_hours_midnight_wrap():
    watch = make_watch(quiet_start="22:00", quiet_end="07:00")
    assert in_quiet_hours(watch, datetime(2026, 10, 17, 23, 0), "UTC") is True
    assert in_quiet_hours(watch, datetime(2026, 10, 17, 3, 0), "UTC") is True
    assert in_quiet_hours(watch, datetime(2026, 10, 17, 12, 0), "UTC") is False
    # boundary: starts at quiet_start, ends before quiet_end
    assert in_quiet_hours(watch, datetime(2026, 10, 17, 22, 0), "UTC") is True
    assert in_quiet_hours(watch, datetime(2026, 10, 17, 7, 0), "UTC") is False


def test_quiet_hours_unset_or_equal_means_no_window():
    assert in_quiet_hours(make_watch(), NOW, "UTC") is False
    watch = make_watch(quiet_start="08:00", quiet_end="08:00")
    assert in_quiet_hours(watch, NOW, "UTC") is False
    watch2 = make_watch(quiet_start="garbage", quiet_end="07:00")
    assert in_quiet_hours(watch2, NOW, "UTC") is False
