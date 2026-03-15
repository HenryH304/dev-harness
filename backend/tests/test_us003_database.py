"""Tests for US-003: SQLite database setup and migrations."""

import datetime
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base, get_engine, get_session, init_db
from app.models import AgentRegistry, Event, Note, Setting, Ticket, TicketDependency


@pytest.fixture
async def engine() -> AsyncGenerator[object, None]:
    """Create a fresh in-memory SQLite engine for each test."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: object) -> AsyncGenerator[AsyncSession, None]:
    """Create a session bound to the test engine."""
    from sqlalchemy.ext.asyncio import AsyncEngine

    assert isinstance(engine, AsyncEngine)
    async with AsyncSession(engine, expire_on_commit=False) as sess:
        yield sess


# --- Table existence tests ---


class TestTablesExist:
    """Verify all required tables are created."""

    async def test_tickets_table_exists(self, engine: object) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "tickets" in tables

    async def test_notes_table_exists(self, engine: object) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "notes" in tables

    async def test_events_table_exists(self, engine: object) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "events" in tables

    async def test_agent_registry_table_exists(self, engine: object) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "agent_registry" in tables

    async def test_settings_table_exists(self, engine: object) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "settings" in tables

    async def test_ticket_dependencies_table_exists(self, engine: object) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(engine, AsyncEngine)
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "ticket_dependencies" in tables


# --- Ticket model tests ---


class TestTicketModel:
    """Test Ticket table schema and functionality."""

    async def test_create_ticket(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="test-project",
            title="Test ticket",
            description="A test ticket",
            acceptance_criteria=["criterion 1", "criterion 2"],
            priority=1,
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)

        assert ticket.id is not None
        assert ticket.project == "test-project"
        assert ticket.title == "Test ticket"
        assert ticket.description == "A test ticket"
        assert ticket.acceptance_criteria == ["criterion 1", "criterion 2"]
        assert ticket.priority == 1
        assert ticket.state == "to_do"

    async def test_ticket_default_state(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="proj", title="T", description="D", acceptance_criteria=[], priority=1
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        assert ticket.state == "to_do"

    async def test_ticket_state_values(self, session: AsyncSession) -> None:
        """Test that all valid states can be stored."""
        valid_states = [
            "to_do",
            "in_progress",
            "ready_for_review",
            "in_review",
            "ready_for_test",
            "in_test",
            "ready_to_merge",
            "done",
            "blocked",
        ]
        for i, state in enumerate(valid_states):
            ticket = Ticket(
                project="proj",
                title=f"Ticket {i}",
                description="D",
                acceptance_criteria=[],
                priority=1,
                state=state,
            )
            session.add(ticket)
        await session.commit()

    async def test_ticket_has_all_fields(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="proj",
            title="Full ticket",
            description="Desc",
            acceptance_criteria=["a"],
            priority=1,
            state="to_do",
            branch_name="ticket/123",
            worktree_path="/tmp/wt",
            current_agent="agent-1",
            agent_attempts=2,
            developer_timeouts=1,
            reviewer_timeouts=0,
            tester_timeouts=0,
            merger_timeouts=0,
            review_rejection_count=1,
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)

        assert ticket.branch_name == "ticket/123"
        assert ticket.worktree_path == "/tmp/wt"
        assert ticket.current_agent == "agent-1"
        assert ticket.agent_attempts == 2
        assert ticket.developer_timeouts == 1
        assert ticket.reviewer_timeouts == 0
        assert ticket.tester_timeouts == 0
        assert ticket.merger_timeouts == 0
        assert ticket.review_rejection_count == 1

    async def test_ticket_timestamps(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="proj", title="T", description="D", acceptance_criteria=[], priority=1
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        assert ticket.created_at is not None
        assert ticket.updated_at is not None
        assert isinstance(ticket.created_at, datetime.datetime)
        assert isinstance(ticket.updated_at, datetime.datetime)

    async def test_ticket_assigned_at_nullable(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="proj", title="T", description="D", acceptance_criteria=[], priority=1
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        assert ticket.assigned_at is None


# --- Note model tests ---


class TestNoteModel:
    """Test Note table schema and functionality."""

    async def test_create_note(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="proj", title="T", description="D", acceptance_criteria=[], priority=1
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)

        note = Note(
            ticket_id=ticket.id,
            author="developer-1",
            content="Progress update",
            note_type="progress",
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)

        assert note.id is not None
        assert note.ticket_id == ticket.id
        assert note.author == "developer-1"
        assert note.content == "Progress update"
        assert note.note_type == "progress"
        assert note.created_at is not None

    async def test_note_types(self, session: AsyncSession) -> None:
        """All note types can be stored."""
        ticket = Ticket(
            project="proj", title="T", description="D", acceptance_criteria=[], priority=1
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)

        for note_type in ["progress", "failure", "review", "test_result", "general"]:
            note = Note(
                ticket_id=ticket.id,
                author="agent",
                content=f"{note_type} note",
                note_type=note_type,
            )
            session.add(note)
        await session.commit()


# --- Event model tests ---


class TestEventModel:
    """Test Event table schema and functionality."""

    async def test_create_event(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="proj", title="T", description="D", acceptance_criteria=[], priority=1
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)

        event = Event(
            ticket_id=ticket.id,
            event_type="ticket_state_changed",
            previous_state="to_do",
            new_state="in_progress",
            agent_id="dev-1",
            payload={"extra": "info"},
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        assert event.id is not None
        assert event.ticket_id == ticket.id
        assert event.event_type == "ticket_state_changed"
        assert event.previous_state == "to_do"
        assert event.new_state == "in_progress"
        assert event.agent_id == "dev-1"
        assert event.payload == {"extra": "info"}
        assert event.created_at is not None


# --- AgentRegistry model tests ---


class TestAgentRegistryModel:
    """Test AgentRegistry table schema and functionality."""

    async def test_create_agent(self, session: AsyncSession) -> None:
        agent = AgentRegistry(
            agent_type="developer",
            status="available",
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        assert agent.id is not None
        assert agent.agent_type == "developer"
        assert agent.status == "available"
        assert agent.current_ticket_id is None
        assert agent.started_at is None

    async def test_agent_busy_with_ticket(self, session: AsyncSession) -> None:
        ticket = Ticket(
            project="proj", title="T", description="D", acceptance_criteria=[], priority=1
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)

        agent = AgentRegistry(
            agent_type="developer",
            status="busy",
            current_ticket_id=ticket.id,
            started_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        assert agent.status == "busy"
        assert agent.current_ticket_id == ticket.id
        assert agent.started_at is not None


# --- Settings model tests ---


class TestSettingsModel:
    """Test Settings table schema and functionality."""

    async def test_create_setting(self, session: AsyncSession) -> None:
        setting = Setting(
            key="max_agents_system",
            value="10",
        )
        session.add(setting)
        await session.commit()
        await session.refresh(setting)

        assert setting.key == "max_agents_system"
        assert setting.value == "10"
        assert setting.updated_at is not None

    async def test_setting_key_is_primary_key(self, session: AsyncSession) -> None:
        setting = Setting(key="test_key", value="v1")
        session.add(setting)
        await session.commit()

        # Updating via merge
        setting2 = Setting(key="test_key", value="v2")
        await session.merge(setting2)
        await session.commit()

        result = await session.get(Setting, "test_key")
        assert result is not None
        assert result.value == "v2"


# --- TicketDependency model tests ---


class TestTicketDependencyModel:
    """Test TicketDependency table schema and functionality."""

    async def test_create_dependency(self, session: AsyncSession) -> None:
        ticket1 = Ticket(
            project="proj", title="T1", description="D", acceptance_criteria=[], priority=1
        )
        ticket2 = Ticket(
            project="proj", title="T2", description="D", acceptance_criteria=[], priority=2
        )
        session.add_all([ticket1, ticket2])
        await session.commit()
        await session.refresh(ticket1)
        await session.refresh(ticket2)

        dep = TicketDependency(
            ticket_id=ticket1.id,
            depends_on_ticket_id=ticket2.id,
        )
        session.add(dep)
        await session.commit()
        await session.refresh(dep)

        assert dep.id is not None
        assert dep.ticket_id == ticket1.id
        assert dep.depends_on_ticket_id == ticket2.id
        assert dep.created_at is not None


# --- Database init tests ---


class TestDatabaseInit:
    """Test database initialization and migration."""

    async def test_init_db_creates_tables(self) -> None:
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        await init_db(eng)

        async with eng.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())

        assert "tickets" in tables
        assert "notes" in tables
        assert "events" in tables
        assert "agent_registry" in tables
        assert "settings" in tables
        assert "ticket_dependencies" in tables

        await eng.dispose()

    async def test_init_db_idempotent(self) -> None:
        """Running init_db twice should not error."""
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        await init_db(eng)
        await init_db(eng)  # Should not raise

        async with eng.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "tickets" in tables

        await eng.dispose()

    async def test_get_engine_returns_engine(self) -> None:
        eng = get_engine("sqlite+aiosqlite:///:memory:")
        assert eng is not None
        await eng.dispose()

    async def test_get_session_yields_session(self) -> None:
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async for sess in get_session(eng):
            assert isinstance(sess, AsyncSession)
            break

        await eng.dispose()
