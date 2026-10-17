"""Notifier plugin interface.

A notifier owns one channel `type` (e.g. 'discord'). Its `config_fields`
drives the generic add-channel form in the UI, so a new notifier (ntfy,
email, ...) is one file with zero UI work.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class FieldSpec:
    name: str
    label: str
    input_type: str = "text"  # text | url | password | number
    required: bool = True
    placeholder: str = ""


@dataclass
class NotifyResult:
    success: bool
    error: str | None = None


class NotifierPlugin(ABC):
    type: str = ""
    display_name: str = ""
    config_fields: list[FieldSpec] = []

    def validate_config(self, config: dict) -> list[str]:
        """Return a list of human-readable problems; empty = valid."""
        problems = []
        for f in self.config_fields:
            if f.required and not str(config.get(f.name, "")).strip():
                problems.append(f"{f.label} is required")
        return problems

    @abstractmethod
    async def send(self, config: dict, message: str) -> NotifyResult:
        ...

    DEFAULT_TEST_MESSAGE = (
        "\U0001f9ea **amp-watchdog** test — this channel is wired up. "
        "Example alerts (each uses the live state at the time):\n"
        "\U0001f534 **Lock Your Door** is **offline** (Stopped)\n"
        "\U0001f4a4 **Lock Your Door** is **sleeping** (Sleeping)\n"
        "\U0001f7e2 **Lock Your Door** is **online** (Ready)"
    )

    async def send_test(self, config: dict, message: str | None = None) -> NotifyResult:
        return await self.send(config, (message or "").strip() or self.DEFAULT_TEST_MESSAGE)
