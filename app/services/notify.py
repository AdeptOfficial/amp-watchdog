"""Message rendering and channel dispatch."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, NotificationLog, Watch
from app.notifiers import get_notifier

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = "{mention} {emoji} **{name}** is **{to_state}** ({app_state})"

_EMOJI = {"online": "\U0001f7e2", "sleeping": "\U0001f4a4", "offline": "\U0001f534"}


class _SafeDict(dict):
    """Unknown placeholders render as themselves instead of raising."""

    def __missing__(self, key):
        return "{" + key + "}"


def render_message(
    watch: Watch, kind: str, from_bucket: str, to_bucket: str, tz_name: str, now: datetime
) -> str:
    template = (watch.message_template or "").strip() or DEFAULT_TEMPLATE
    local = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
    values = _SafeDict(
        name=watch.display_name,
        instance=(watch.config or {}).get("instance_name", watch.target_key),
        from_state=from_bucket,
        to_state=to_bucket,
        app_state=watch.last_app_state_name or "Unknown",
        time=local.strftime("%H:%M"),
        mention=f"<@{watch.mention_id}>" if watch.mention_id else "",
        emoji=_EMOJI.get(to_bucket, ""),
    )
    message = template.format_map(values).strip()
    if kind == "realert":
        message = f"⏰ (still) {message}"
    return message


async def dispatch(db: AsyncSession, watch: Watch, message: str, kind: str) -> None:
    """Send to every enabled channel on the watch; one log row per attempt."""
    ids = [i for i in (watch.channel_ids or []) if isinstance(i, int)]
    if not ids:
        return
    result = await db.execute(select(Channel).where(Channel.id.in_(ids)))
    channels = {c.id: c for c in result.scalars()}
    for channel_id in ids:
        channel = channels.get(channel_id)
        if channel is None or not channel.enabled:
            continue  # dangling/disabled ids are skipped silently
        plugin = get_notifier(channel.type)
        if plugin is None:
            db.add(NotificationLog(
                watch_id=watch.id, channel_id=channel_id, kind=kind,
                success=False, error=f"no notifier plugin for type {channel.type}", message=message,
            ))
            continue
        result_ = await plugin.send(channel.config or {}, message)
        db.add(NotificationLog(
            watch_id=watch.id, channel_id=channel_id, kind=kind,
            success=result_.success, error=result_.error, message=message,
        ))
        if not result_.success:
            logger.warning("Notify failed (watch=%s channel=%s): %s", watch.id, channel.name, result_.error)
