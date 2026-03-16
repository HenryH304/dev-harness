"""Tests for US-024: Dependency visualisation — bulk unresolved dependency endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app
from app.models import Ticket, TicketDependency
from app.routers.dependencies import _get_session as dep_get_session
from app.routers.tickets import _get_session as ticket_get_session


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as sess:
        yield sess


@pytest.fixture
async def client(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncSession:  # type: ignore[misc]
        async with async_session() as sess:
            yield sess

    app.dependency_overrides[ticket_get_session] = override_session
    app.dependency_overrides[dep_get_session] = override_session

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


async def _create_ticket(
    session: AsyncSession, title: str, state: str = "to_do", **kwargs: object
) -> Ticket:
    ticket = Ticket(
        project="test",
        title=title,
        description="desc",
        acceptance_criteria=[],
        priority=1,
        state=state,
        **kwargs,
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def _add_dep(
    session: AsyncSession, ticket_id: int, depends_on_id: int
) -> TicketDependency:
    dep = TicketDependency(ticket_id=ticket_id, depends_on_ticket_id=depends_on_id)
    session.add(dep)
    await session.commit()
    return dep


@pytest.mark.asyncio
async def test_unresolved_empty_when_no_deps(client: AsyncClient, session: AsyncSession):
    """Returns empty dict when no tickets have dependencies."""
    await _create_ticket(session, "Ticket A")
    resp = await client.get("/api/dependencies/unresolved")
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_unresolved_returns_blocking_ticket_ids(
    client: AsyncClient, session: AsyncSession
):
    """Returns unresolved dependency ticket IDs for each blocked ticket."""
    t1 = await _create_ticket(session, "Ticket A", state="to_do")
    t2 = await _create_ticket(session, "Ticket B", state="to_do")
    t3 = await _create_ticket(session, "Ticket C", state="to_do")
    # t3 depends on t1 and t2
    await _add_dep(session, t3.id, t1.id)
    await _add_dep(session, t3.id, t2.id)

    resp = await client.get("/api/dependencies/unresolved")
    assert resp.status_code == 200
    data = resp.json()
    assert str(t3.id) in data
    assert sorted(data[str(t3.id)]) == sorted([t1.id, t2.id])


@pytest.mark.asyncio
async def test_unresolved_excludes_done_deps(
    client: AsyncClient, session: AsyncSession
):
    """Does not include dependencies that are in done state."""
    t1 = await _create_ticket(session, "Ticket A", state="done")
    t2 = await _create_ticket(session, "Ticket B", state="to_do")
    t3 = await _create_ticket(session, "Ticket C", state="to_do")
    await _add_dep(session, t3.id, t1.id)  # resolved (done)
    await _add_dep(session, t3.id, t2.id)  # unresolved

    resp = await client.get("/api/dependencies/unresolved")
    data = resp.json()
    assert str(t3.id) in data
    assert data[str(t3.id)] == [t2.id]


@pytest.mark.asyncio
async def test_unresolved_omits_fully_resolved_tickets(
    client: AsyncClient, session: AsyncSession
):
    """Tickets with all deps in done state are not in the response."""
    t1 = await _create_ticket(session, "Ticket A", state="done")
    t2 = await _create_ticket(session, "Ticket B", state="to_do")
    await _add_dep(session, t2.id, t1.id)

    resp = await client.get("/api/dependencies/unresolved")
    data = resp.json()
    assert str(t2.id) not in data


@pytest.mark.asyncio
async def test_unresolved_multiple_tickets(
    client: AsyncClient, session: AsyncSession
):
    """Multiple tickets with unresolved deps all appear in response."""
    t1 = await _create_ticket(session, "Blocker", state="to_do")
    t2 = await _create_ticket(session, "A", state="to_do")
    t3 = await _create_ticket(session, "B", state="to_do")
    await _add_dep(session, t2.id, t1.id)
    await _add_dep(session, t3.id, t1.id)

    resp = await client.get("/api/dependencies/unresolved")
    data = resp.json()
    assert str(t2.id) in data
    assert str(t3.id) in data
    assert data[str(t2.id)] == [t1.id]
    assert data[str(t3.id)] == [t1.id]
