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

    async def send_test(self, config: dict) -> NotifyResult:
        return await self.send(config, "🔔 amp-watchdog test notification — channel works!")
