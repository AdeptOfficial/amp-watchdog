"""Discord webhook notifier."""

import httpx

from app.core.notifier_base import FieldSpec, NotifierPlugin, NotifyResult

DISCORD_MAX = 1900  # leave headroom under the 2000-char hard limit


class DiscordNotifier(NotifierPlugin):
    type = "discord"
    display_name = "Discord webhook"
    config_fields = [
        FieldSpec(
            name="webhook_url",
            label="Webhook URL",
            input_type="url",
            required=True,
            placeholder="https://discord.com/api/webhooks/...",
        ),
    ]

    def validate_config(self, config: dict) -> list[str]:
        problems = super().validate_config(config)
        url = str(config.get("webhook_url", ""))
        if url and not url.startswith("https://discord.com/api/webhooks/"):
            problems.append("Webhook URL should start with https://discord.com/api/webhooks/")
        return problems

    async def send(self, config: dict, message: str) -> NotifyResult:
        url = config.get("webhook_url", "")
        if not url:
            return NotifyResult(success=False, error="no webhook_url configured")
        content = message if len(message) <= DISCORD_MAX else message[: DISCORD_MAX - 1] + "…"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json={"content": content})
            if resp.is_success:
                return NotifyResult(success=True)
            return NotifyResult(success=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")
        except httpx.HTTPError as e:
            return NotifyResult(success=False, error=repr(e))
