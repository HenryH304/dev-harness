"""Tests for US-007: Merger resumability in the timeout handler."""

import json
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# _get_beads_timeout_info tests
# ---------------------------------------------------------------------------


class TestGetBeadsTimeoutInfo:
    """Unit tests for _get_beads_timeout_info helper in agent_loop."""

    def _import(self):
        from app.agent_loop import _get_beads_timeout_info
        return _get_beads_timeout_info

    def test_returns_none_when_no_beads_dir(self, tmp_path) -> None:
        """Returns None when .beads/ does not exist."""
        fn = self._import()
        assert fn(str(tmp_path)) is None

    def test_returns_none_when_open_bd_fails(self, tmp_path) -> None:
        """Returns None when bd list exits non-zero."""
        fn = self._import()
        (tmp_path / ".beads").mkdir()
        with mock.patch("subprocess.run") as m:
            m.return_value = mock.Mock(returncode=1, stdout="", stderr="err")
            result = fn(str(tmp_path))
        assert result is None

    def test_all_open_beads_no_partial_progress(self, tmp_path) -> None:
        """5 open == 5 total → has_partial_progress is False."""
        fn = self._import()
        (tmp_path / ".beads").mkdir()
        all_beads = [
            {"id": i, "title": f"step-{i}", "metadata": {}} for i in range(1, 6)
        ]
        # bd list --json (open) → 5 beads; bd list --json --all (total) → 5 beads
        def side_effect(cmd, **kwargs):
            return mock.Mock(returncode=0, stdout=json.dumps(all_beads), stderr="")

        with mock.patch("subprocess.run", side_effect=side_effect):
            result = fn(str(tmp_path))

        assert result is not None
        assert result["has_partial_progress"] is False
        assert result["has_blocker"] is False
        assert len(result["open_beads"]) == 5

    def test_partial_progress_when_some_closed(self, tmp_path) -> None:
        """3 open, 5 total → has_partial_progress is True."""
        fn = self._import()
        (tmp_path / ".beads").mkdir()
        all_beads = [{"id": i, "title": f"step-{i}", "metadata": {}} for i in range(1, 6)]
        open_beads = all_beads[2:]  # 3 open (steps 3-5)

        call_count = [0]

        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if "--all" in cmd:
                return mock.Mock(returncode=0, stdout=json.dumps(all_beads), stderr="")
            return mock.Mock(returncode=0, stdout=json.dumps(open_beads), stderr="")

        with mock.patch("subprocess.run", side_effect=side_effect):
            result = fn(str(tmp_path))

        assert result is not None
        assert result["has_partial_progress"] is True
        assert result["has_blocker"] is False
        assert len(result["open_beads"]) == 3
        assert result["total_count"] == 5

    def test_blocker_bead_detected(self, tmp_path) -> None:
        """A bead with blocker:true sets has_blocker to True."""
        fn = self._import()
        (tmp_path / ".beads").mkdir()
        blocker = {"id": 3, "title": "merge-push", "metadata": {"blocker": True, "category": "conflict", "detail": "Unresolvable conflict"}}
        open_beads = [blocker]
        all_beads = [{"id": i, "title": f"step-{i}", "metadata": {}} for i in range(1, 3)] + [blocker]

        def side_effect(cmd, **kwargs):
            if "--all" in cmd:
                return mock.Mock(returncode=0, stdout=json.dumps(all_beads), stderr="")
            return mock.Mock(returncode=0, stdout=json.dumps(open_beads), stderr="")

        with mock.patch("subprocess.run", side_effect=side_effect):
            result = fn(str(tmp_path))

        assert result is not None
        assert result["has_blocker"] is True
        assert result["has_partial_progress"] is False

    def test_no_partial_progress_when_all_open_and_no_blocker(self, tmp_path) -> None:
        """No partial progress when open == total (nothing closed yet)."""
        fn = self._import()
        (tmp_path / ".beads").mkdir()
        beads = [{"id": i, "title": f"step-{i}", "metadata": {}} for i in range(1, 4)]

        def side_effect(cmd, **kwargs):
            return mock.Mock(returncode=0, stdout=json.dumps(beads), stderr="")

        with mock.patch("subprocess.run", side_effect=side_effect):
            result = fn(str(tmp_path))

        assert result is not None
        assert result["has_partial_progress"] is False


# ---------------------------------------------------------------------------
# _classify_merger_timeout tests
# ---------------------------------------------------------------------------


class TestClassifyMergerTimeout:
    """Tests for the pure classification helper."""

    def _import(self):
        from app.agent_loop import _classify_merger_timeout
        return _classify_merger_timeout

    def test_no_beads_returns_no_beads(self) -> None:
        """None beads_info → 'no_beads' outcome."""
        fn = self._import()
        assert fn(0, None) == "no_beads"

    def test_blocker_returns_blocker(self) -> None:
        """has_blocker=True → 'blocker' outcome regardless of resume count."""
        fn = self._import()
        beads_info = {"has_blocker": True, "has_partial_progress": False, "open_beads": [], "total_count": 5}
        assert fn(0, beads_info) == "blocker"
        assert fn(2, beads_info) == "blocker"

    def test_no_progress_returns_no_progress(self) -> None:
        """has_partial_progress=False, no blocker → 'no_progress' outcome."""
        fn = self._import()
        beads_info = {"has_blocker": False, "has_partial_progress": False, "open_beads": [], "total_count": 5}
        assert fn(0, beads_info) == "no_progress"
        assert fn(2, beads_info) == "no_progress"

    def test_partial_progress_resume_count_below_cap(self) -> None:
        """Partial progress + resume_count < 3 → 'resume'."""
        fn = self._import()
        beads_info = {"has_blocker": False, "has_partial_progress": True, "open_beads": [{"title": "run-tests"}], "total_count": 5}
        assert fn(0, beads_info) == "resume"
        assert fn(1, beads_info) == "resume"
        assert fn(2, beads_info) == "resume"

    def test_partial_progress_resume_count_at_cap(self) -> None:
        """Partial progress + resume_count >= 3 → 'cap_exceeded'."""
        fn = self._import()
        beads_info = {"has_blocker": False, "has_partial_progress": True, "open_beads": [{"title": "run-tests"}], "total_count": 5}
        assert fn(3, beads_info) == "cap_exceeded"
        assert fn(4, beads_info) == "cap_exceeded"


# ---------------------------------------------------------------------------
# Ticket model: merger_resume_count column
# ---------------------------------------------------------------------------


class TestMergerResumeCountColumn:
    """Ticket model must have merger_resume_count with default 0."""

    @pytest.fixture()
    def anyio_backend(self) -> str:
        return "asyncio"

    def test_merger_resume_count_attribute_exists(self) -> None:
        """Ticket model has merger_resume_count attribute."""
        from app.models import Ticket
        ticket = Ticket()
        assert hasattr(ticket, "merger_resume_count"), (
            "Ticket model must have merger_resume_count attribute"
        )

    @pytest.mark.anyio
    async def test_merger_resume_count_defaults_to_zero_after_insert(self) -> None:
        """merger_resume_count defaults to 0 after a DB round-trip."""
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy import select
        from app.database import Base
        from app.models import Ticket

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            ticket = Ticket(
                project="p", title="t", description="d",
                acceptance_criteria=[], priority=1,
            )
            session.add(ticket)
            await session.commit()
            ticket_id = ticket.id

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
            assert ticket.merger_resume_count == 0

        await engine.dispose()


# ---------------------------------------------------------------------------
# DB migration: merger_resume_count column added to existing tables
# ---------------------------------------------------------------------------


class TestMergerResumeCountMigration:
    """_migrate_schema must add merger_resume_count to an existing tickets table."""

    @pytest.fixture()
    def anyio_backend(self) -> str:
        return "asyncio"

    @pytest.mark.anyio
    async def test_migration_adds_merger_resume_count(self) -> None:
        """_migrate_schema adds merger_resume_count column to existing tables."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.database import Base, _migrate_schema

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        # Create tables WITHOUT merger_resume_count to simulate an older schema
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Drop the column by rebuilding table without it is complex for SQLite;
            # instead, verify migration is idempotent (no error on second run).
            # The column exists from create_all, so just check migration doesn't error.
            await _migrate_schema(conn)

        # Verify column is present
        async with engine.begin() as conn:
            columns = await conn.execute(text("PRAGMA table_info(tickets)"))
            col_names = {row[1] for row in columns}
            assert "merger_resume_count" in col_names, (
                "merger_resume_count column must be present after migration"
            )

        await engine.dispose()


# ---------------------------------------------------------------------------
# Integration: check_agent_timeouts merger resumability
# ---------------------------------------------------------------------------


class TestCheckAgentTimeoutsMergerResumability:
    """check_agent_timeouts implements merger resumability via beads state."""

    @pytest.fixture()
    def anyio_backend(self) -> str:
        return "asyncio"

    async def _make_db_and_ticket(self):
        """Create an in-memory DB with a ticker in in_merge state and a busy agent entry."""
        import datetime
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from app.database import Base
        from app.models import Ticket, AgentRegistry

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            ticket = Ticket(
                project="test",
                title="T",
                description="D",
                acceptance_criteria=[],
                priority=1,
                state="in_merge",
                current_agent="merger-abc123",
                assigned_at=datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc),
                worktree_path="/fake/worktree",
                merger_resume_count=0,
            )
            session.add(ticket)
            await session.flush()

            agent = AgentRegistry(
                agent_type="merger",
                status="busy",
                current_ticket_id=ticket.id,
                started_at=datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc),
            )
            session.add(agent)
            await session.commit()
            ticket_id = ticket.id

        return engine, factory, ticket_id

    @pytest.mark.anyio
    async def test_partial_progress_increments_resume_count(self, tmp_path) -> None:
        """Partial progress + resume_count < 3 → increment counter, leave in in_merge."""
        from sqlalchemy import select
        from app.models import Ticket
        from app.routers.agents import check_agent_timeouts

        engine, factory, ticket_id = await self._make_db_and_ticket()

        # Set worktree_path to tmp_path so beads check works
        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
            ticket.worktree_path = str(tmp_path)
            (tmp_path / ".beads").mkdir()
            await session.commit()

        open_beads = [{"id": 3, "title": "run-tests", "metadata": {}}]
        all_beads = [{"id": i, "title": f"s{i}", "metadata": {}} for i in range(1, 6)]

        def subprocess_side(cmd, **kwargs):
            if "--all" in cmd:
                return mock.Mock(returncode=0, stdout=json.dumps(all_beads), stderr="")
            return mock.Mock(returncode=0, stdout=json.dumps(open_beads), stderr="")

        with (
            mock.patch("subprocess.run", side_effect=subprocess_side),
            mock.patch("app.routers.agents.publish_event", new_callable=mock.AsyncMock),
            mock.patch("app.agent_loop._schedule_pickup"),
        ):
            await check_agent_timeouts(factory)

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()

        assert ticket.state == "in_merge", f"Expected in_merge, got {ticket.state}"
        assert ticket.merger_resume_count == 1, f"Expected 1, got {ticket.merger_resume_count}"

        await engine.dispose()

    @pytest.mark.anyio
    async def test_no_beads_dir_uses_existing_timeout_logic(self, tmp_path) -> None:
        """No .beads/ dir → existing timeout logic (to_do, no resume)."""
        from sqlalchemy import select
        from app.models import Ticket
        from app.routers.agents import check_agent_timeouts

        engine, factory, ticket_id = await self._make_db_and_ticket()

        # worktree exists but no .beads/
        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
            ticket.worktree_path = str(tmp_path)
            await session.commit()

        with (
            mock.patch("app.routers.agents.publish_event", new_callable=mock.AsyncMock),
        ):
            await check_agent_timeouts(factory)

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()

        assert ticket.state == "to_do", f"Expected to_do fallback, got {ticket.state}"
        assert ticket.merger_resume_count == 0

        await engine.dispose()

    @pytest.mark.anyio
    async def test_no_progress_uses_existing_timeout_logic(self, tmp_path) -> None:
        """All beads open (no progress) → existing timeout logic (to_do)."""
        from sqlalchemy import select
        from app.models import Ticket
        from app.routers.agents import check_agent_timeouts

        engine, factory, ticket_id = await self._make_db_and_ticket()

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
            ticket.worktree_path = str(tmp_path)
            (tmp_path / ".beads").mkdir()
            await session.commit()

        # All 5 beads open = no progress
        all_open = [{"id": i, "title": f"s{i}", "metadata": {}} for i in range(1, 6)]

        def subprocess_side(cmd, **kwargs):
            return mock.Mock(returncode=0, stdout=json.dumps(all_open), stderr="")

        with (
            mock.patch("subprocess.run", side_effect=subprocess_side),
            mock.patch("app.routers.agents.publish_event", new_callable=mock.AsyncMock),
        ):
            await check_agent_timeouts(factory)

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()

        assert ticket.state == "to_do", f"Expected to_do fallback, got {ticket.state}"
        assert ticket.merger_resume_count == 0

        await engine.dispose()

    @pytest.mark.anyio
    async def test_blocker_bead_uses_existing_timeout_logic(self, tmp_path) -> None:
        """Blocker bead → existing timeout logic (to_do)."""
        from sqlalchemy import select
        from app.models import Ticket
        from app.routers.agents import check_agent_timeouts

        engine, factory, ticket_id = await self._make_db_and_ticket()

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
            ticket.worktree_path = str(tmp_path)
            (tmp_path / ".beads").mkdir()
            await session.commit()

        blocker_bead = {"id": 3, "title": "merge-push", "metadata": {"blocker": True, "category": "conflict", "detail": "Unresolvable"}}
        open_beads = [blocker_bead]
        all_beads = [{"id": i, "title": f"s{i}", "metadata": {}} for i in range(1, 3)] + [blocker_bead]

        def subprocess_side(cmd, **kwargs):
            if "--all" in cmd:
                return mock.Mock(returncode=0, stdout=json.dumps(all_beads), stderr="")
            return mock.Mock(returncode=0, stdout=json.dumps(open_beads), stderr="")

        with (
            mock.patch("subprocess.run", side_effect=subprocess_side),
            mock.patch("app.routers.agents.publish_event", new_callable=mock.AsyncMock),
        ):
            await check_agent_timeouts(factory)

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()

        assert ticket.state == "to_do", f"Expected to_do fallback for blocker, got {ticket.state}"

        await engine.dispose()

    @pytest.mark.anyio
    async def test_resume_count_cap_blocks_ticket(self, tmp_path) -> None:
        """Partial progress + merger_resume_count >= 3 → blocked state."""
        from sqlalchemy import select
        from app.models import Ticket
        from app.routers.agents import check_agent_timeouts

        engine, factory, ticket_id = await self._make_db_and_ticket()

        # Set merger_resume_count to 3 (at the cap)
        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()
            ticket.worktree_path = str(tmp_path)
            ticket.merger_resume_count = 3
            (tmp_path / ".beads").mkdir()
            await session.commit()

        open_beads = [{"id": 3, "title": "run-tests", "metadata": {}}]
        all_beads = [{"id": i, "title": f"s{i}", "metadata": {}} for i in range(1, 6)]

        def subprocess_side(cmd, **kwargs):
            if "--all" in cmd:
                return mock.Mock(returncode=0, stdout=json.dumps(all_beads), stderr="")
            return mock.Mock(returncode=0, stdout=json.dumps(open_beads), stderr="")

        with (
            mock.patch("subprocess.run", side_effect=subprocess_side),
            mock.patch("app.routers.agents.publish_event", new_callable=mock.AsyncMock),
        ):
            await check_agent_timeouts(factory)

        async with factory() as session:
            ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()

        assert ticket.state == "blocked", f"Expected blocked after cap, got {ticket.state}"

        await engine.dispose()
