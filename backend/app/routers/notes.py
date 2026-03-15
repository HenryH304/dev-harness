"""Notes and comments API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Note, Ticket
from app.schemas import NoteCreate, NoteResponse

router = APIRouter(prefix="/api/tickets", tags=["notes"])


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


@router.post("/{ticket_id}/notes", response_model=NoteResponse, status_code=201)
async def create_note(
    ticket_id: int,
    note_in: NoteCreate,
    session: AsyncSession = Depends(_get_session),
) -> Note:
    """Create a note on a ticket."""
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    note = Note(
        ticket_id=ticket_id,
        author=note_in.author,
        content=note_in.content,
        note_type=note_in.note_type,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


@router.get("/{ticket_id}/notes", response_model=list[NoteResponse])
async def list_notes(
    ticket_id: int,
    session: AsyncSession = Depends(_get_session),
) -> list[Note]:
    """Get all notes for a ticket, ordered by created_at descending."""
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    notes_result = await session.execute(
        select(Note)
        .where(Note.ticket_id == ticket_id)
        .order_by(Note.created_at.desc(), Note.id.desc())
    )
    return list(notes_result.scalars().all())
