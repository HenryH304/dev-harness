"""Ticket CRUD API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Note, Ticket
from app.schemas import (
    NoteResponse,
    TicketCreate,
    TicketDetailResponse,
    TicketResponse,
    TicketUpdate,
)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


@router.post("", response_model=TicketResponse, status_code=201)
async def create_ticket(
    ticket_in: TicketCreate,
    session: AsyncSession = Depends(_get_session),
) -> Ticket:
    ticket = Ticket(
        project=ticket_in.project,
        title=ticket_in.title,
        description=ticket_in.description,
        acceptance_criteria=ticket_in.acceptance_criteria,
        priority=ticket_in.priority,
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


@router.get("", response_model=list[TicketResponse])
async def list_tickets(
    project: str | None = None,
    state: str | None = None,
    session: AsyncSession = Depends(_get_session),
) -> list[Ticket]:
    stmt = select(Ticket)
    if project is not None:
        stmt = stmt.where(Ticket.project == project)
    if state is not None:
        stmt = stmt.where(Ticket.state == state)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(_get_session),
) -> TicketDetailResponse:
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    notes_result = await session.execute(
        select(Note).where(Note.ticket_id == ticket_id).order_by(Note.created_at.desc())
    )
    notes = list(notes_result.scalars().all())

    return TicketDetailResponse(
        **{c.key: getattr(ticket, c.key) for c in Ticket.__table__.columns},
        notes=[NoteResponse.model_validate(n) for n in notes],
    )


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: int,
    ticket_in: TicketUpdate,
    session: AsyncSession = Depends(_get_session),
) -> Ticket:
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    update_data = ticket_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ticket, field, value)

    await session.commit()
    await session.refresh(ticket)
    return ticket


@router.delete("/{ticket_id}")
async def delete_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, str]:
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    await session.delete(ticket)
    await session.commit()
    return {"status": "deleted"}
