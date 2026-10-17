"""Due-watch scheduler: a single asyncio ticker over `next_check_at`.

Why not APScheduler: per-watch intervals are DB rows edited at runtime; the
DB is the single source of truth and survives restarts for free. Due watches
are grouped by type so one tick issues ONE backend call per checker (the AMP
checker resolves all its watches from a single GetInstances response).
"""

import asyncio
import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import or_, select

from app.checkers import get_checker
from app.config import settings
from app.core.broadcaster import broadcaster
from app.core.checker_base import CheckResult
from app.database import async_session
from app.models import Transition, Watch, utcnow
from app.services.evaluator import evaluate
from app.services.notify import dispatch, render_message

logger = logging.getLogger(__name__)

# Set by the "Check now" endpoint to cut the tick sleep short
wake_event = asyncio.Event()


def request_immediate_sweep() -> None:
    wake_event.set()


async def run_due_checks(session_factory=None, now=None) -> list[int]:
    """One sweep: check all due watches, persist outcomes, broadcast changes.

    Returns the ids of watches that were checked.
    """
    session_factory = session_factory or async_session
    now = now or utcnow()
    checked_ids: list[int] = []

    async with session_factory() as db:
        result = await db.execute(
            select(Watch).where(
                Watch.enabled.is_(True),
                or_(Watch.next_check_at.is_(None), Watch.next_check_at <= now),
            )
        )
        due = list(result.scalars())
        if not due:
            return []

        by_type: dict[str, list[Watch]] = defaultdict(list)
        for watch in due:
            by_type[watch.type].append(watch)

        for type_, group in by_type.items():
            checker = get_checker(type_)
            interval = lambda w: timedelta(  # noqa: E731
                seconds=w.check_interval_seconds or settings.DEFAULT_CHECK_INTERVAL
            )

            if checker is None:
                for w in group:
                    w.last_checked_at = now
                    w.consecutive_errors = (w.consecutive_errors or 0) + 1
                    w.last_error = f"no checker loaded for type '{type_}'"
                    w.next_check_at = now + interval(w)
                    checked_ids.append(w.id)
                continue

            try:
                results = await checker.check(group)
            except Exception as e:
                # Backend unreachable is NOT evidence the targets are offline:
                # record the error, advance the schedule, no transitions.
                logger.warning("Checker '%s' failed for %d watches: %r", type_, len(group), e)
                for w in group:
                    w.last_checked_at = now
                    w.consecutive_errors = (w.consecutive_errors or 0) + 1
                    w.last_error = str(e)
                    w.next_check_at = now + interval(w)
                    checked_ids.append(w.id)
                continue

            for w in group:
                check_result = results.get(w.id) or CheckResult(
                    bucket="unknown", raw_state_name="Unknown", error="checker returned no result"
                )
                outcome = evaluate(w, check_result, now, settings.TZ)
                if outcome.transition is not None:
                    db.add(Transition(watch_id=w.id, created_at=now, **outcome.transition))
                if outcome.notify_kind:
                    message = render_message(
                        w, outcome.notify_kind, outcome.from_bucket, outcome.to_bucket,
                        settings.TZ, now,
                    )
                    await dispatch(db, w, message, outcome.notify_kind)
                w.next_check_at = now + interval(w)
                checked_ids.append(w.id)

        await db.commit()

    for watch_id in checked_ids:
        await broadcaster.broadcast("watch_update", {"id": watch_id})
    return checked_ids


async def scheduler_loop() -> None:
    logger.info("Scheduler started (tick=%ss)", settings.SCHEDULER_TICK)
    while True:
        try:
            await asyncio.wait_for(wake_event.wait(), timeout=settings.SCHEDULER_TICK)
        except asyncio.TimeoutError:
            pass
        wake_event.clear()
        try:
            await run_due_checks()
        except Exception:
            logger.exception("Scheduler sweep failed")
