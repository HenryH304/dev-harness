"""Agent pickup and locking system."""

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import get_agent_config
from app.config import load_config
from app.database import get_session
from app.models import AgentRegistry, Setting, Ticket
from app.redis_client import get_redis, publish_event
from app.schemas import TicketResponse

router = APIRouter(prefix="/api/agents", tags=["agents"])

# State the ticket transitions to when picked up by each agent type
PICKUP_NEXT_STATE: dict[str, str] = {
    "developer": "in_progress",
    "reviewer": "in_review",
    "tester": "in_test",
    "merger": "ready_to_merge",  # no "in_merge" state — stays until done
}

# WIP reduction priority: higher number = higher priority when near cap
WIP_PRIORITY: dict[str, int] = {
    "developer": 1,
    "reviewer": 2,
    "tester": 3,
    "merger": 4,
}


async def _get_session() -> AsyncSession:  # type: ignore[misc]
    """Get a database session using the app engine."""
    from app.main import engine

    async for session in get_session(engine):
        yield session


async def acquire_lock(ticket_id: int, agent_id: str, ttl: int = 30) -> bool:
    """Acquire a Redis distributed lock for a ticket.

    Uses SET NX EX pattern to prevent concurrent pickup.
    Returns True if lock was acquired, False otherwise.
    """
    client = await get_redis()
    result = await client.set(
        f"lock:ticket:{ticket_id}", agent_id, nx=True, ex=ttl
    )
    return result is not None


@router.post("/pickup/{agent_type}", response_model=TicketResponse)
async def pickup_ticket(
    agent_type: str,
    session: AsyncSession = Depends(_get_session),
) -> Ticket:
    """Find and claim the next available ticket for an agent type."""
    # Validate agent type
    try:
        agent_config = get_agent_config(agent_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {agent_type}")

    config = load_config()

    # Check system-wide agent cap
    busy_count_result = await session.execute(
        select(AgentRegistry).where(AgentRegistry.status == "busy")
    )
    busy_agents = list(busy_count_result.scalars().all())
    busy_count = len(busy_agents)

    # WIP reduction: when at or near cap, only allow higher-priority agent types
    if busy_count >= config.max_agents_system:
        raise HTTPException(
            status_code=429,
            detail="System at capacity — no agent slots available",
        )

    # When near cap (1 slot left), enforce WIP priority
    if busy_count >= config.max_agents_system - 1:
        # Only allow if this agent type has higher WIP priority than the lowest
        agent_wip = WIP_PRIORITY.get(agent_type, 0)
        if agent_wip <= 1:  # developer is lowest priority
            raise HTTPException(
                status_code=429,
                detail="System near capacity — only higher-priority agent types allowed",
            )

    # Get active priority project
    priority_project: str | None = None
    setting_result = await session.execute(
        select(Setting).where(Setting.key == "active_priority_project")
    )
    setting = setting_result.scalar_one_or_none()
    if setting is not None:
        priority_project = setting.value

    # Find candidate tickets:
    # - In the agent type's column binding state
    # - Not already assigned (current_agent is NULL)
    column_state = agent_config.column_binding
    query = (
        select(Ticket)
        .where(Ticket.state == column_state)
        .where(Ticket.current_agent.is_(None))
    )

    # Order: priority project first, then by priority (ascending = higher priority)
    if priority_project:
        query = query.order_by(
            case(
                (Ticket.project == priority_project, 0),
                else_=1,
            ),
            Ticket.priority.asc(),
            Ticket.id.asc(),
        )
    else:
        query = query.order_by(Ticket.priority.asc(), Ticket.id.asc())

    result = await session.execute(query)
    candidates = list(result.scalars().all())

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No available tickets for agent type '{agent_type}'",
        )

    # Try to acquire lock on each candidate
    agent_id = f"{agent_type}-{uuid.uuid4().hex[:8]}"
    picked_ticket: Ticket | None = None

    for ticket in candidates:
        if await acquire_lock(ticket.id, agent_id):
            picked_ticket = ticket
            break

    if picked_ticket is None:
        raise HTTPException(
            status_code=409,
            detail="All candidate tickets are locked by other agents",
        )

    # Update ticket state
    next_state = PICKUP_NEXT_STATE.get(agent_type, column_state)
    previous_state = picked_ticket.state
    if next_state != previous_state:
        picked_ticket.state = next_state
    picked_ticket.current_agent = agent_id
    picked_ticket.assigned_at = datetime.datetime.now(datetime.timezone.utc)
    picked_ticket.agent_attempts += 1

    # Register agent in agent_registry
    agent_entry = AgentRegistry(
        agent_type=agent_type,
        status="busy",
        current_ticket_id=picked_ticket.id,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(agent_entry)

    await session.commit()
    await session.refresh(picked_ticket)

    # Publish agent_assigned event
    await publish_event(
        "ticket:events",
        {
            "event_type": "agent_assigned",
            "ticket_id": picked_ticket.id,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "previous_state": previous_state,
            "new_state": picked_ticket.state,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )

    return picked_ticket
