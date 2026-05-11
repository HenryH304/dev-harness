"""Tests for US-001: DB migration ready_to_merge → ready_for_merge."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.models  # register models with Base.metadata before create_all  # noqa: F401
from app.database import Base, _migrate_schema


@pytest.fixture()
async def conn():  # type: ignore[misc]
    """Async connection to in-memory SQLite with all tables created.

    Uses a single persistent connection so DDL and DML share the same
    in-memory database (SQLite in-memory DBs are connection-scoped).
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    c = await engine.connect()
    await c.run_sync(Base.metadata.create_all)
    await c.commit()
    yield c
    await c.close()
    await engine.dispose()


_INSERT = (
    "INSERT INTO tickets "
    "(project, title, description, priority, state, acceptance_criteria, "
    " agent_attempts, developer_timeouts, reviewer_timeouts, tester_timeouts, "
    " merger_timeouts, developer_failure_count, review_rejection_count, tester_rejection_count) "
    "VALUES ('p', '{title}', 'd', 1, '{state}', '[]', 0, 0, 0, 0, 0, 0, 0, 0)"
)

_INSERT_WITH_PREV = (
    "INSERT INTO tickets "
    "(project, title, description, priority, state, previous_state, acceptance_criteria, "
    " agent_attempts, developer_timeouts, reviewer_timeouts, tester_timeouts, "
    " merger_timeouts, developer_failure_count, review_rejection_count, tester_rejection_count) "
    "VALUES ('p', '{title}', 'd', 1, '{state}', '{prev}', '[]', 0, 0, 0, 0, 0, 0, 0, 0)"
)


async def test_migrate_state_ready_to_merge_renamed(conn) -> None:
    """Rows with state='ready_to_merge' are updated to 'ready_for_merge'."""
    await conn.execute(text(_INSERT.format(title="t", state="ready_to_merge")))
    await _migrate_schema(conn)
    row = await conn.execute(text("SELECT state FROM tickets WHERE title = 't'"))
    assert row.scalar_one() == "ready_for_merge"


async def test_migrate_previous_state_ready_to_merge_renamed(conn) -> None:
    """Rows with previous_state='ready_to_merge' are updated to 'ready_for_merge'."""
    await conn.execute(
        text(_INSERT_WITH_PREV.format(title="t2", state="in_merge", prev="ready_to_merge"))
    )
    await _migrate_schema(conn)
    row = await conn.execute(text("SELECT previous_state FROM tickets WHERE title = 't2'"))
    assert row.scalar_one() == "ready_for_merge"


async def test_migrate_idempotent(conn) -> None:
    """Running _migrate_schema twice leaves state as 'ready_for_merge' (idempotent)."""
    await conn.execute(text(_INSERT.format(title="t3", state="ready_to_merge")))
    await _migrate_schema(conn)
    await _migrate_schema(conn)
    row = await conn.execute(text("SELECT state FROM tickets WHERE title = 't3'"))
    assert row.scalar_one() == "ready_for_merge"


async def test_migrate_unaffected_states_unchanged(conn) -> None:
    """Rows in states other than 'ready_to_merge' are not affected."""
    await conn.execute(text(_INSERT.format(title="t4", state="in_test")))
    await _migrate_schema(conn)
    row = await conn.execute(text("SELECT state FROM tickets WHERE title = 't4'"))
    assert row.scalar_one() == "in_test"
