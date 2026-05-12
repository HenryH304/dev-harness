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

    columns = await conn.execute(text("PRAGMA table_info(tickets)"))
    existing = {row[1] for row in columns}
    ticket_migrations = [
        ("tester_rejection_count", "INTEGER NOT NULL DEFAULT 0"),
        ("developer_failure_count", "INTEGER NOT NULL DEFAULT 0"),
        ("previous_state", "VARCHAR(50)"),
        ("merger_resume_count", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, definition in ticket_migrations:
        if col not in existing:
            await conn.execute(
                text(f"ALTER TABLE tickets ADD COLUMN {col} {definition}")
            )

    # Rename legacy state values
    await conn.execute(
        text("UPDATE tickets SET state = 'ready_for_merge' WHERE state = 'ready_to_merge'")
    )
    await conn.execute(
        text(
            "UPDATE tickets SET previous_state = 'ready_for_merge'"
            " WHERE previous_state = 'ready_to_merge'"
        )
    )

    proj_columns = await conn.execute(text("PRAGMA table_info(projects)"))
    existing_proj = {row[1] for row in proj_columns}
    if "sort_order" not in existing_proj:
        await conn.execute(text("ALTER TABLE projects ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"))
        # Back-fill existing projects with sequential order based on name
        await conn.execute(text(
            "UPDATE projects SET sort_order = (SELECT COUNT(*) FROM projects p2 WHERE p2.name <= projects.name)"
        ))


async def get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for database operations."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
