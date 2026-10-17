"""Checker plugin interface.

A checker owns one watch `type` (e.g. 'amp'). The check() signature is a
BATCH on purpose: the AMP checker resolves every due watch with a single
GetInstances call per tick, however many instances are watched.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Watch


@dataclass
class CheckResult:
    bucket: str                      # online | sleeping | offline | transitional | unknown
    raw_state: int | None = None     # checker-native state code (AMP AppState)
    raw_state_name: str = "Unknown"
    error: str | None = None


@dataclass
class DiscoveredTarget:
    """A watchable thing the checker found, for the UI picker."""
    target_key: str
    name: str
    meta: dict = field(default_factory=dict)


class CheckerPlugin(ABC):
    type: str = ""
    display_name: str = ""

    async def discover(self) -> list[DiscoveredTarget]:
        """Targets available to watch; checkers without discovery return []."""
        return []

    @abstractmethod
    async def check(self, watches: "list[Watch]") -> dict[int, CheckResult]:
        """Check a batch of watches of this type; keyed by watch.id.

        Connection-level failures (the whole backend unreachable) should
        raise — the scheduler records them as errors without inventing
        offline transitions. Per-target problems (one instance missing)
        return a CheckResult with bucket='unknown' and an error string.
        """
        ...
