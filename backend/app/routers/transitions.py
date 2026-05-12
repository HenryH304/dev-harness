"""State transition API with validation."""

import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Event, Note, Ticket, TicketDependency
from app.redis_client import publish_event
from app.schemas import TicketResponse, TransitionRequest

router = APIRouter(prefix="/api/tickets", tags=["transitions"])

# Valid state transitions: from_state -> set of allowed to_states
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "to_do": {"in_progress", "blocked"},
    "in_progress": {"ready_for_review", "blocked"},
    "ready_for_review": {"in_review", "blocked"},
    "in_review": {"ready_for_test", "blocked"},
    "ready_for_test": {"in_test", "blocked"},
    "in_test": {"ready_for_merge", "blocked"},
    "ready_for_merge": {"in_merge", "blocked"},
    "in_merge": {"done", "blocked"},
    "done": {"blocked"},
    "blocked": set(),  # blocked requires manual_override
}

ALL_STATES = set(ALLOWED_TRANSITIONS.keys())


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


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


@router.post("/{ticket_id}/transition", response_model=TicketResponse)
async def transition_ticket(
    ticket_id: int,
    transition: TransitionRequest,
    session: AsyncSession = Depends(_get_session),
) -> Ticket:
    """Transition a ticket to a new state with validation."""
    # Validate new_state is a known state
    if transition.new_state not in ALL_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state: {transition.new_state}",
        )

    # Fetch ticket
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    previous_state = ticket.state

    # Same state check
    if transition.new_state == previous_state:
        raise HTTPException(
            status_code=400,
            detail=f"Ticket is already in state '{previous_state}'. "
            f"Invalid transition.",
        )

    # Blocked ticket check
    if previous_state == "blocked" and not transition.manual_override:
        raise HTTPException(
            status_code=400,
            detail="Ticket is blocked. Use manual_override to transition.",
        )

    # For blocked tickets with manual_override, allow transition to any valid state
    if previous_state != "blocked":
        allowed = ALLOWED_TRANSITIONS.get(previous_state, set())
        if transition.new_state not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid transition from '{previous_state}' "
                f"to '{transition.new_state}'",
            )

    # Dependency check for transitions past to_do (except to blocked)
    if (
        transition.new_state != "blocked"
        and transition.new_state != "to_do"
        and await _has_unresolved_dependencies(session, ticket_id)
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot transition: unresolved dependencies exist",
        )

    # Perform the transition
    ticket.state = transition.new_state

    # Reset failure counters when a human manually unblocks a ticket so agents
    # get a fresh set of retries rather than immediately re-blocking.
    if previous_state == "blocked":
        blocked_from = ticket.previous_state or ""
        if blocked_from in ("in_progress", "to_do"):
            ticket.developer_failure_count = 0
        elif blocked_from in ("in_review", "ready_for_review"):
            ticket.review_rejection_count = 0
        elif blocked_from in ("in_test", "ready_for_test"):
            ticket.tester_rejection_count = 0

    # Auto-generate note
    if transition.new_state == "blocked":
        note_content = f"Ticket blocked (was: '{previous_state}')"
        if transition.note:
            note_content += f"\n\nReason: {transition.note}"
        note_type = "failure"
    else:
        note_content = f"State changed from '{previous_state}' to '{transition.new_state}'"
        if transition.note:
            note_content += f"\n\n{transition.note}"
        note_type = "progress"

    note = Note(
        ticket_id=ticket_id,
        author=transition.agent_id or "system",
        content=note_content,
        note_type=note_type,
    )
    session.add(note)

    # Create event record
    event = Event(
        ticket_id=ticket_id,
        event_type="ticket_state_changed",
        previous_state=previous_state,
        new_state=transition.new_state,
        agent_id=transition.agent_id,
        payload={"note": transition.note} if transition.note else None,
    )
    session.add(event)

    await session.commit()
    await session.refresh(ticket)

    # Publish to Redis
    await publish_event(
        "ticket:events",
        {
            "event_type": "ticket_state_changed",
            "ticket_id": ticket_id,
            "previous_state": previous_state,
            "new_state": transition.new_state,
            "agent_id": transition.agent_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )

    return ticket
