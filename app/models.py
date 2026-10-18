"""Database models.

Design notes:
- Watches are checker-agnostic: `type` discriminates (only 'amp' today) and
  `target_key` is the checker-scoped identity (AMP: InstanceID guid).
- Per-watch runtime state lives on the same row (no joins on the hot path).
- JSON columns instead of junction tables (add-column-only migration policy).
- All datetimes are naive UTC.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    """Naive UTC now (SQLite stores naive datetimes)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def default_notify_rules() -> dict:
    """Alert on anything going offline and on recovery; sleep cycles are routine."""
    return {
        "online->offline": True,
        "sleeping->offline": True,
        "offline->online": True,
        "online->sleeping": False,
        "sleeping->online": False,
        "offline->sleeping": False,
    }


class Watch(Base):
    __tablename__ = "watches"
    __table_args__ = (UniqueConstraint("type", "target_key", name="uq_watch_target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(20), default="amp")
    target_key: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    notify_rules: Mapped[dict] = mapped_column(JSON, default=default_notify_rules)
    channel_ids: Mapped[list] = mapped_column(JSON, default=list)
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    mention_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    realert_minutes: Mapped[int] = mapped_column(Integer, default=0)  # 0 = off
    quiet_start: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM" local
    quiet_end: Mapped[str | None] = mapped_column(String(5), nullable=True)

    # Runtime state
    last_bucket: Mapped[str] = mapped_column(String(20), default="unknown")  # last STABLE bucket
    last_app_state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_app_state_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_change_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Consecutive liveness-ping failures (ping target lives in config as
    # ping_host/ping_port); at PING_FAIL_THRESHOLD the checker reports offline
    ping_fail_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[str] = mapped_column(String(20), default="discord")
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # schema owned by the notifier plugin
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    test_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # None = built-in preview
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Transition(Base):
    __tablename__ = "transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watches.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    from_bucket: Mapped[str] = mapped_column(String(20))
    to_bucket: Mapped[str] = mapped_column(String(20))
    from_state_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_state_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    suppress_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("watches.id", ondelete="SET NULL"), nullable=True
    )
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # transition | realert | test
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
