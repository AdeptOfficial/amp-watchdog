"""AMP checker: resolves every due AMP watch with ONE GetInstances call."""

import logging
from typing import TYPE_CHECKING

from app.clients.amp import get_amp_client
from app.core.checker_base import CheckerPlugin, CheckResult, DiscoveredTarget
from app.core.states import bucket_of, state_name

if TYPE_CHECKING:
    from app.models import Watch

logger = logging.getLogger(__name__)


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
        for watch in watches:
            inst = instances.get(watch.target_key)
            if inst is None:
                results[watch.id] = CheckResult(
                    bucket="unknown",
                    raw_state=None,
                    raw_state_name="NotVisible",
                    error="instance not visible in GetInstances (deleted, or missing Manage permission?)",
                )
            else:
                results[watch.id] = CheckResult(
                    bucket=bucket_of(inst.app_state),
                    raw_state=inst.app_state,
                    raw_state_name=state_name(inst.app_state),
                )
        return results
