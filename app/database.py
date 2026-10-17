"""SQLite database setup with SQLAlchemy async.

Same house pattern as status-tracker: WAL mode + create_all + an
add-column-only migration dict instead of Alembic (homelab trade-off:
columns can be added, never modified or removed).
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# sqlite:/// (relative) and sqlite://// (absolute) both preserved
database_url = settings.DATABASE_URL
if database_url.startswith("sqlite://"):
    database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)

engine = create_async_engine(
    database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async_session = async_session_maker


async def get_db() -> AsyncSession:
    """FastAPI dependency."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def run_migrations(conn):
    """Add missing columns to existing tables (create_all only makes new tables)."""

    def get_existing_columns(connection):
        inspector = inspect(connection)
        return {
            table: {col["name"] for col in inspector.get_columns(table)}
            for table in inspector.get_table_names()
        }

    existing_schema = await conn.run_sync(get_existing_columns)

    # table -> column -> (type, default); add entries here when models grow columns
    migrations: dict[str, dict[str, tuple[str, str]]] = {
        "channels": {
            "test_message": ("TEXT", "NULL"),
        },
    }

    for table_name, columns in migrations.items():
        if table_name not in existing_schema:
            continue
        for column_name, (column_type, default) in columns.items():
            if column_name not in existing_schema[table_name]:
                default_clause = f"DEFAULT {default}" if default else ""
                logger.info("Migration: adding column %s.%s", table_name, column_name)
                await conn.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} {default_clause}")
                )


async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.run_sync(Base.metadata.create_all)
        await run_migrations(conn)
    logger.info("Database initialized with WAL mode")
