"""AMP checker: resolves every due AMP watch with ONE GetInstances call.

Watches may additionally configure a liveness ping (config ping_host +
ping_port): a real Minecraft server-list-ping against the player-facing
port. AMP's AppState alone cannot see a wedged wake-on-connect sleep
listener (port open, no status response, AMP still says Sleeping — the
2026-10-17 LYD incident), so when AMP claims online/sleeping AND a ping
target is set, both sources must agree. PING_FAIL_THRESHOLD consecutive
ping failures override the bucket to offline ("port dead"), which rides
the normal transition/alert machinery.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from app.clients.amp import get_amp_client
from app.config import settings
from app.core import mcping
from app.core.checker_base import CheckerPlugin, CheckResult, DiscoveredTarget
from app.core.states import BUCKET_ONLINE, BUCKET_SLEEPING, bucket_of, state_name

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)


def _ping_target(watch: "Watch") -> tuple[str, int] | None:
    config = watch.config or {}
    host = str(config.get("ping_host") or "").strip()
    try:
        port = int(config.get("ping_port") or 0)
    except (TypeError, ValueError):
        return None
    if not host or not (0 < port < 65536):
        return None
    return host, port


class AMPChecker(CheckerPlugin):
    type = "amp"
    display_name = "AMP instance"

    async def discover(self) -> list[DiscoveredTarget]:
        instances = await get_amp_client().get_instances()
        return [
            DiscoveredTarget(
                target_key=i.instance_id,
                name=i.friendly_name,
                meta={
                    "instance_name": i.instance_name,
                    "module": i.module,
                    "app_state": i.app_state,
                    "app_state_name": state_name(i.app_state),
                    "bucket": bucket_of(i.app_state),
                },
            )
            for i in instances
        ]

    async def check(self, watches: "list[Watch]") -> dict[int, CheckResult]:
        # AMPConnectionError/AMPAuthError propagate: the scheduler records
        # them as check errors instead of fabricating offline transitions.
        instances = {i.instance_id: i for i in await get_amp_client().get_instances()}
        results: dict[int, CheckResult] = {}
        to_ping: list[tuple["Watch", tuple[str, int]]] = []

        for watch in watches:
            inst = instances.get(watch.target_key)
            if inst is None:
                results[watch.id] = CheckResult(
                    bucket="unknown",
                    raw_state=None,
                    raw_state_name="NotVisible",
                    error="instance not visible in GetInstances (deleted, or missing Manage permission?)",
                )
                continue
            results[watch.id] = CheckResult(
                bucket=bucket_of(inst.app_state),
                raw_state=inst.app_state,
                raw_state_name=state_name(inst.app_state),
            )
            # Only online/sleeping claims need corroborating: a healthy
            # instance answers SLP in both states, and probing transitional
            # states (Starting, PreparingForSleep, ...) would just flap.
            target = _ping_target(watch)
            if target is not None and results[watch.id].bucket in (BUCKET_ONLINE, BUCKET_SLEEPING):
                to_ping.append((watch, target))

        if to_ping:
            alive_flags = await asyncio.gather(*(
                mcping.probe(host, port, timeout=settings.PING_TIMEOUT_SECONDS)
                for _, (host, port) in to_ping
            ))
            for (watch, (host, port)), alive in zip(to_ping, alive_flags):
                result = results[watch.id]
                if alive:
                    watch.ping_fail_count = 0
                    continue
                watch.ping_fail_count = (watch.ping_fail_count or 0) + 1
                if watch.ping_fail_count >= settings.PING_FAIL_THRESHOLD:
                    logger.warning(
                        "Watch %s: AMP says %s but %s:%s failed SLP %d times — reporting offline",
                        watch.display_name, result.raw_state_name, host, port, watch.ping_fail_count,
                    )
                    results[watch.id] = CheckResult(
                        bucket="offline",
                        raw_state=result.raw_state,
                        raw_state_name=f"{result.raw_state_name} (port dead)",
                        error=(
                            f"AMP reports {result.raw_state_name} but {host}:{port} has not "
                            f"answered a status ping {watch.ping_fail_count}x — listener wedged?"
                        ),
                    )
                else:
                    result.error = (
                        f"liveness ping {host}:{port} failed "
                        f"({watch.ping_fail_count}/{settings.PING_FAIL_THRESHOLD})"
                    )
        return results
