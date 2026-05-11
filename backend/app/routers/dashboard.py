"""Dashboard endpoints for agent monitoring, metrics, and manual controls."""

import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import AgentRegistry, Note, Setting, Ticket
from app.redis_client import publish_event

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


# --- Response models ---


class ActiveAgentResponse(BaseModel):
    id: int
    agent_type: str
    status: str
    current_ticket_id: int | None
    ticket_title: str | None
    started_at: datetime.datetime | None
    elapsed_seconds: float | None


class AgentsListResponse(BaseModel):
    agents: list[ActiveAgentResponse]


class ColumnCounts(BaseModel):
    to_do: int = 0
    in_progress: int = 0
    ready_for_review: int = 0
    in_review: int = 0
    ready_for_test: int = 0
    in_test: int = 0
    ready_to_merge: int = 0
    done: int = 0
    blocked: int = 0


class MetricsResponse(BaseModel):
    column_counts: ColumnCounts
    total_tickets: int


class TimeoutAnalyticsResponse(BaseModel):
    developer_timeouts: int
    reviewer_timeouts: int
    tester_timeouts: int
    merger_timeouts: int


class BlockedTicketResponse(BaseModel):
    id: int
    title: str
    project: str
    state: str
    review_rejection_count: int
    agent_attempts: int
    last_failure_note: str | None

    model_config = {"from_attributes": True}


class BlockedListResponse(BaseModel):
    blocked_tickets: list[BlockedTicketResponse]


class ToggleAgentsRequest(BaseModel):
    paused: bool


class ToggleAgentsResponse(BaseModel):
    agents_paused: bool


# --- Endpoints ---


@router.get("/agents", response_model=AgentsListResponse)
async def get_active_agents(
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """Get all busy agents with their current ticket info and elapsed time."""
    result = await session.execute(
        select(AgentRegistry).where(AgentRegistry.status == "busy")
    )
    busy_agents = list(result.scalars().all())

    now = datetime.datetime.now(datetime.timezone.utc)
    agents_data: list[dict[str, Any]] = []

    for agent in busy_agents:
        ticket_title: str | None = None
        if agent.current_ticket_id is not None:
            ticket_result = await session.execute(
                select(Ticket.title).where(Ticket.id == agent.current_ticket_id)
            )
            ticket_title = ticket_result.scalar_one_or_none()

        elapsed: float | None = None
        if agent.started_at is not None:
            started = agent.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=datetime.timezone.utc)
            elapsed = (now - started).total_seconds()

        agents_data.append(
            {
                "id": agent.id,
                "agent_type": agent.agent_type,
                "status": agent.status,
                "current_ticket_id": agent.current_ticket_id,
                "ticket_title": ticket_title,
                "started_at": agent.started_at,
                "elapsed_seconds": elapsed,
            }
        )

    return {"agents": agents_data}


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """Get workflow metrics: ticket count per column."""
    all_states = [
        "to_do", "in_progress", "ready_for_review", "in_review",
        "ready_for_test", "in_test", "ready_to_merge", "done", "blocked",
    ]

    result = await session.execute(
        select(Ticket.state, func.count(Ticket.id)).group_by(Ticket.state)
    )
    counts_raw = {row[0]: row[1] for row in result.all()}

    column_counts = {state: counts_raw.get(state, 0) for state in all_states}
    total = sum(column_counts.values())

    return {"column_counts": column_counts, "total_tickets": total}


@router.get("/timeouts", response_model=TimeoutAnalyticsResponse)
async def get_timeout_analytics(
    session: AsyncSession = Depends(_get_session),
) -> dict[str, int]:
    """Get aggregated timeout counts per agent type across all tickets."""
    result = await session.execute(
        select(
            func.coalesce(func.sum(Ticket.developer_timeouts), 0),
            func.coalesce(func.sum(Ticket.reviewer_timeouts), 0),
            func.coalesce(func.sum(Ticket.tester_timeouts), 0),
            func.coalesce(func.sum(Ticket.merger_timeouts), 0),
        )
    )
    row = result.one()
    return {
        "developer_timeouts": int(row[0]),
        "reviewer_timeouts": int(row[1]),
        "tester_timeouts": int(row[2]),
        "merger_timeouts": int(row[3]),
    }


@router.get("/blocked", response_model=BlockedListResponse)
async def get_blocked_tickets(
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """Get all blocked/failed tickets with rejection counts."""
    result = await session.execute(
        select(Ticket).where(Ticket.state == "blocked").order_by(Ticket.id.desc())
    )
    tickets = list(result.scalars().all())

    blocked_data: list[dict[str, Any]] = []
    for ticket in tickets:
        # Get last failure note
        note_result = await session.execute(
            select(Note.content)
            .where(Note.ticket_id == ticket.id, Note.note_type == "failure")
            .order_by(Note.id.desc())
            .limit(1)
        )
        last_note = note_result.scalar_one_or_none()

        blocked_data.append(
            {
                "id": ticket.id,
                "title": ticket.title,
                "project": ticket.project,
                "state": ticket.state,
                "review_rejection_count": ticket.review_rejection_count,
                "agent_attempts": ticket.agent_attempts,
                "last_failure_note": last_note,
            }
        )

    return {"blocked_tickets": blocked_data}


@router.post("/force-unlock/{ticket_id}")
async def force_unlock_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """Force unlock a stuck ticket: release agent, return to to_do."""
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Blocked tickets have already had their agent released — still allow unlock
    if ticket.current_agent is None and ticket.state != "blocked":
        raise HTTPException(status_code=400, detail="Ticket has no assigned agent")

    previous_state = ticket.state
    agent_id = ticket.current_agent

    # Release any lingering agent registry entry
    if agent_id:
        agent_result = await session.execute(
            select(AgentRegistry).where(
                AgentRegistry.current_ticket_id == ticket.id,
                AgentRegistry.status == "busy",
            )
        )
        agent_entry = agent_result.scalar_one_or_none()
        if agent_entry:
            agent_entry.status = "available"
            agent_entry.current_ticket_id = None

    # Determine the right target state.
    # For blocked tickets, use previous_state (state before blocking).
    # For stuck-active tickets (agent assigned but never completed), use current state.
    _UNLOCK_TARGET: dict[str, str] = {
        "in_progress":      "to_do",
        "in_review":        "ready_for_review",
        "in_test":          "ready_for_test",
        "to_do":            "to_do",
        "ready_for_review": "ready_for_review",
        "ready_for_test":   "ready_for_test",
        "ready_to_merge":   "ready_to_merge",
    }
    if ticket.state == "blocked":
        lookup_state = ticket.previous_state or "to_do"
    else:
        lookup_state = ticket.state
    new_state = _UNLOCK_TARGET.get(lookup_state, "to_do")

    # Reset the failure counter that caused (or contributed to) the block
    # so the ticket gets a fresh set of retries after manual intervention.
    if lookup_state in ("in_progress", "to_do"):
        ticket.developer_failure_count = 0
    elif lookup_state in ("in_review", "ready_for_review"):
        ticket.review_rejection_count = 0
    elif lookup_state in ("in_test", "ready_for_test"):
        ticket.tester_rejection_count = 0

    ticket.previous_state = previous_state
    ticket.current_agent = None
    ticket.assigned_at = None
    ticket.state = new_state

    note_content = (
        f"Force unlocked by admin. Returned to '{new_state}'. "
        f"{'Agent ' + agent_id + ' released. ' if agent_id else ''}"
        "Failure counter reset."
    )
    note = Note(
        ticket_id=ticket_id,
        author="system",
        content=note_content,
        note_type="general",
    )
    session.add(note)

    await session.commit()
    await session.refresh(ticket)

    await publish_event(
        "ticket:events",
        {
            "event_type": "ticket_state_changed",
            "ticket_id": ticket_id,
            "previous_state": previous_state,
            "new_state": new_state,
            "agent_id": agent_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )

    return {
        "id": ticket.id,
        "title": ticket.title,
        "state": ticket.state,
        "current_agent": ticket.current_agent,
    }


@router.post("/toggle-agents", response_model=ToggleAgentsResponse)
async def toggle_agents(
    payload: ToggleAgentsRequest,
    session: AsyncSession = Depends(_get_session),
) -> dict[str, bool]:
    """Pause or resume all agent processing."""
    # Store pause state in settings
    result = await session.execute(
        select(Setting).where(Setting.key == "agents_paused")
    )
    setting = result.scalar_one_or_none()

    if setting is None:
        setting = Setting(key="agents_paused", value=str(payload.paused).lower())
        session.add(setting)
    else:
        setting.value = str(payload.paused).lower()

    await session.commit()

    return {"agents_paused": payload.paused}
