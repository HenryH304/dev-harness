"""Ticket dependency management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Ticket, TicketDependency
from app.schemas import (
    DependencyCreate,
    DependencyListResponse,
    DependencyResponse,
    TicketSummary,
)

router = APIRouter(prefix="/api/tickets", tags=["dependencies"])


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


async def _detect_cycle(
    session: AsyncSession, ticket_id: int, depends_on_id: int
) -> bool:
    """Return True if adding ticket_id -> depends_on_id would create a cycle.

    Uses BFS: starting from depends_on_id, follow its dependencies.
    If we reach ticket_id, there's a cycle.
    """
    visited: set[int] = set()
    queue: list[int] = [depends_on_id]

    while queue:
        current = queue.pop(0)
        if current == ticket_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        result = await session.execute(
            select(TicketDependency.depends_on_ticket_id).where(
                TicketDependency.ticket_id == current
            )
        )
        for (dep_id,) in result.all():
            if dep_id not in visited:
                queue.append(dep_id)

    return False


async def _has_unresolved_dependencies(
    session: AsyncSession, ticket_id: int
) -> bool:
    """Return True if ticket has dependencies not in 'done' state."""
    result = await session.execute(
        select(TicketDependency.depends_on_ticket_id).where(
            TicketDependency.ticket_id == ticket_id
        )
    )
    dep_ids = [row[0] for row in result.all()]
    if not dep_ids:
        return False

    for dep_id in dep_ids:
        ticket_result = await session.execute(
            select(Ticket.state).where(Ticket.id == dep_id)
        )
        row = ticket_result.one_or_none()
        if row is None or row[0] != "done":
            return True

    return False


@router.post(
    "/{ticket_id}/dependencies",
    response_model=DependencyResponse,
    status_code=201,
)
async def add_dependency(
    ticket_id: int,
    dep_in: DependencyCreate,
    session: AsyncSession = Depends(_get_session),
) -> TicketDependency:
    # Self-reference check
    if ticket_id == dep_in.depends_on_ticket_id:
        raise HTTPException(status_code=400, detail="A ticket cannot depend on itself")

    # Verify both tickets exist
    ticket = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    if ticket.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    dep_ticket = await session.execute(
        select(Ticket).where(Ticket.id == dep_in.depends_on_ticket_id)
    )
    if dep_ticket.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dependency ticket not found")

    # Duplicate check
    existing = await session.execute(
        select(TicketDependency).where(
            and_(
                TicketDependency.ticket_id == ticket_id,
                TicketDependency.depends_on_ticket_id == dep_in.depends_on_ticket_id,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Dependency already exists")

    # Cycle detection
    if await _detect_cycle(session, ticket_id, dep_in.depends_on_ticket_id):
        raise HTTPException(
            status_code=400,
            detail="Circular dependency detected",
        )

    dep = TicketDependency(
        ticket_id=ticket_id,
        depends_on_ticket_id=dep_in.depends_on_ticket_id,
    )
    session.add(dep)
    await session.commit()
    await session.refresh(dep)
    return dep


@router.delete("/{ticket_id}/dependencies/{dep_id}")
async def delete_dependency(
    ticket_id: int,
    dep_id: int,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    result = await session.execute(
        select(TicketDependency).where(
            and_(
                TicketDependency.id == dep_id,
                TicketDependency.ticket_id == ticket_id,
            )
        )
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=404, detail="Dependency not found")

    await session.delete(dep)
    await session.commit()
    return {"status": "deleted"}


@router.get("/{ticket_id}/dependencies", response_model=DependencyListResponse)
async def get_dependencies(
    ticket_id: int,
    session: AsyncSession = Depends(_get_session),
) -> DependencyListResponse:
    # Verify ticket exists
    ticket_result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    if ticket_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # blocked_by: tickets this ticket depends on
    blocked_by_result = await session.execute(
        select(Ticket)
        .join(
            TicketDependency,
            TicketDependency.depends_on_ticket_id == Ticket.id,
        )
        .where(TicketDependency.ticket_id == ticket_id)
    )
    blocked_by = [
        TicketSummary.model_validate(t)
        for t in blocked_by_result.scalars().all()
    ]

    # blocks: tickets that depend on this ticket
    blocks_result = await session.execute(
        select(Ticket)
        .join(
            TicketDependency,
            TicketDependency.ticket_id == Ticket.id,
        )
        .where(TicketDependency.depends_on_ticket_id == ticket_id)
    )
    blocks = [
        TicketSummary.model_validate(t)
        for t in blocks_result.scalars().all()
    ]

    return DependencyListResponse(blocked_by=blocked_by, blocks=blocks)
