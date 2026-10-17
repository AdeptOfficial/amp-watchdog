"""Transition / notification decision logic — the testable heart of the app.

Stable-bucket model: `watch.last_bucket` only ever holds a STABLE bucket
(online/sleeping/offline, plus the initial 'unknown'). Transitional states
(Starting, Restarting, ...) update the raw display fields but never create
transitions or alerts, so a routine restart produces zero noise.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.checker_base import CheckResult
from app.core.states import BUCKET_OFFLINE, STABLE_BUCKETS
from app.models import Watch


@dataclass
class EvalOutcome:
    # Transition row data (None = no transition recorded this check)
    transition: dict | None = None
    # 'transition' | 'realert' | None
    notify_kind: str | None = None
    from_bucket: str = ""
    to_bucket: str = ""


def _parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(watch: Watch, now_utc: datetime, tz_name: str) -> bool:
    """now_utc is naive UTC; quiet window is in local wall-clock time.

    A window where start == end (or either end is unset/invalid) is no window.
    start > end spans midnight (e.g. 22:00 -> 07:00).
    """
    start = _parse_hhmm(watch.quiet_start)
    end = _parse_hhmm(watch.quiet_end)
    if start is None or end is None or start == end:
        return False
    local = now_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).time()
    if start < end:
        return start <= local < end
    return local >= start or local < end


def evaluate(watch: Watch, result: CheckResult, now: datetime, tz_name: str) -> EvalOutcome:
    """Apply a check result to a watch (mutates its runtime fields) and
    decide whether to record a transition and/or notify."""
    prev_stable = watch.last_bucket or "unknown"
    prev_state_name = watch.last_app_state_name

    watch.last_checked_at = now
    watch.last_app_state = result.raw_state
    watch.last_app_state_name = result.raw_state_name
    if result.error:
        watch.consecutive_errors = (watch.consecutive_errors or 0) + 1
        watch.last_error = result.error
    else:
        watch.consecutive_errors = 0
        watch.last_error = None

    new_bucket = result.bucket
    if new_bucket not in STABLE_BUCKETS:
        # Transitional/unknown: display-only, never alerts, never clobbers last_bucket
        return EvalOutcome(from_bucket=prev_stable, to_bucket=new_bucket)

    quiet = in_quiet_hours(watch, now, tz_name)

    if new_bucket != prev_stable:
        watch.last_bucket = new_bucket
        watch.last_change_at = now

        rule_key = f"{prev_stable}->{new_bucket}"
        rule_on = bool((watch.notify_rules or {}).get(rule_key, False))
        if not rule_on:
            reason = "rule_off"
        elif not (watch.channel_ids or []):
            reason = "no_channels"
        elif quiet:
            reason = "quiet_hours"
        else:
            reason = None

        transition = {
            "from_bucket": prev_stable,
            "to_bucket": new_bucket,
            "from_state_name": prev_state_name,
            "to_state_name": result.raw_state_name,
            "notified": reason is None,
            "suppress_reason": reason,
        }
        if reason is None:
            watch.last_notified_at = now
            return EvalOutcome(transition, "transition", prev_stable, new_bucket)
        return EvalOutcome(transition, None, prev_stable, new_bucket)

    # Unchanged stable bucket: maybe re-alert while still offline
    if (
        new_bucket == BUCKET_OFFLINE
        and (watch.realert_minutes or 0) > 0
        and (watch.channel_ids or [])
        and not quiet
    ):
        anchor = watch.last_notified_at or watch.last_change_at
        if anchor is not None and now - anchor >= timedelta(minutes=watch.realert_minutes):
            watch.last_notified_at = now
            return EvalOutcome(None, "realert", new_bucket, new_bucket)

    return EvalOutcome(from_bucket=prev_stable, to_bucket=new_bucket)
