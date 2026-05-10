"""SQLite database setup with SQLAlchemy async engine."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def get_engine(url: str = "sqlite+aiosqlite:///data/devharness.db") -> AsyncEngine:
    """Create and return an async SQLAlchemy engine."""
    return create_async_engine(url, echo=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables if they don't exist, then apply column migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_schema(conn)


async def _migrate_schema(conn: Any) -> None:
    """Add missing columns to existing tables (idempotent)."""
    from sqlalchemy import text

    # tester_rejection_count added alongside review_rejection_count equivalent for tester
    columns = await conn.execute(text("PRAGMA table_info(tickets)"))
    existing = {row[1] for row in columns}
    if "tester_rejection_count" not in existing:
        await conn.execute(
            text(
                "ALTER TABLE tickets ADD COLUMN tester_rejection_count INTEGER NOT NULL DEFAULT 0"
            )
        )


async def get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for database operations."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
