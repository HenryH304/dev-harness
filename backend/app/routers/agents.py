"""Agent pickup, completion, failure, and timeout management."""

import asyncio
import datetime
import logging
from pathlib import Path
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.agents import get_agent_config
from app.config import load_config
from app.database import get_session
from app.models import AgentRegistry, Note, Project, Setting, Ticket, TicketDependency
from app.worktree import WorktreeError, create_worktree
from app.redis_client import get_redis, publish_event
from app.schemas import AgentFailRequest, TicketResponse

router = APIRouter(prefix="/api/agents", tags=["agents"])

# State the ticket transitions to when picked up by each agent type
PICKUP_NEXT_STATE: dict[str, str] = {
    "developer": "in_progress",
    "reviewer": "in_review",
    "tester": "in_test",
    "merger": "in_merge",
}

# Forward state transitions on completion
COMPLETE_NEXT_STATE: dict[str, str] = {
    "in_progress": "ready_for_review",
    "in_review": "ready_for_test",
    "in_test": "ready_for_merge",
    "in_merge": "done",
}

# WIP reduction priority: higher number = higher priority when near cap
WIP_PRIORITY: dict[str, int] = {
    "developer": 1,
    "reviewer": 2,
    "tester": 3,
    "merger": 4,
}

# Timeout counter field name per agent type
TIMEOUT_FIELD: dict[str, str] = {
    "developer": "developer_timeouts",
    "reviewer": "reviewer_timeouts",
    "tester": "tester_timeouts",
    "merger": "merger_timeouts",
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


async def _release_agent(
    session: AsyncSession, ticket: Ticket
) -> None:
    """Release agent lock from ticket and update agent registry."""
    agent_id = ticket.current_agent
    ticket.current_agent = None
    ticket.assigned_at = None

    if agent_id:
        # Update agent registry entry
        result = await session.execute(
            select(AgentRegistry).where(
                AgentRegistry.current_ticket_id == ticket.id,
                AgentRegistry.status == "busy",
            )
        )
        agent_entry = result.scalar_one_or_none()
        if agent_entry:
            agent_entry.status = "available"
            agent_entry.current_ticket_id = None


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

    # Load all DB settings in one query and merge into config
    all_settings_result = await session.execute(select(Setting))
    db_overrides = {row.key: row.value for row in all_settings_result.scalars().all()}
    config = load_config(db_overrides=db_overrides)

    # Honour global dispatch kill-switch
    if db_overrides.get("agent_dispatch_enabled", "true") == "false":
        raise HTTPException(
            status_code=429,
            detail="Agent dispatch is paused — resume via the board controls",
        )

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

    # Check per-agent-type concurrency cap
    per_type_cap = config.max_agents_per_type.get(agent_type)
    if per_type_cap is not None:
        busy_type_count_result = await session.execute(
            select(AgentRegistry).where(
                AgentRegistry.status == "busy",
                AgentRegistry.agent_type == agent_type,
            )
        )
        busy_type_count = len(list(busy_type_count_result.scalars().all()))
        if busy_type_count >= per_type_cap:
            raise HTTPException(
                status_code=429,
                detail=f"Agent type '{agent_type}' at capacity ({busy_type_count}/{per_type_cap})",
            )

    # Get active priority project from the already-loaded DB settings
    priority_project: str | None = db_overrides.get("active_priority_project")

    # Find candidate tickets:
    # - In the agent type's column binding state
    # - Not already assigned (current_agent is NULL)
    # - No dependency currently in 'blocked' state
    column_state = agent_config.column_binding
    BlockedDep = aliased(Ticket)
    has_blocked_dependency = (
        select(TicketDependency.id)
        .join(BlockedDep, BlockedDep.id == TicketDependency.depends_on_ticket_id)
        .where(
            TicketDependency.ticket_id == Ticket.id,
            BlockedDep.state == "blocked",
        )
        .exists()
    )
    query = (
        select(Ticket)
        .where(Ticket.state == column_state)
        .where(Ticket.current_agent.is_(None))
        .where(~has_blocked_dependency)
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

    # Create git worktree for developer agents when none exists yet
    if agent_type == "developer" and picked_ticket.worktree_path is None:
        project_result = await session.execute(
            select(Project).where(Project.name == picked_ticket.project)
        )
        project = project_result.scalar_one_or_none()
        if project is not None:
            try:
                loop = asyncio.get_running_loop()
                wt = await loop.run_in_executor(
                    None, create_worktree, picked_ticket.id, project.repo_path
                )
                picked_ticket.worktree_path = wt["worktree_path"]
                picked_ticket.branch_name = wt["branch_name"]
            except WorktreeError as exc:
                redis_client = await get_redis()
                await redis_client.delete(f"lock:ticket:{picked_ticket.id}")
                raise HTTPException(
                    status_code=500, detail=f"Failed to create worktree: {exc}"
                )

    # Update ticket state
    next_state = PICKUP_NEXT_STATE.get(agent_type, column_state)
    previous_state = picked_ticket.state
    if next_state != previous_state:
        picked_ticket.previous_state = previous_state
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


def _delete_worktree_background(ticket_id: int, project: str, worktree_path: str) -> None:
    """Best-effort worktree deletion — runs synchronously but is non-fatal."""
    import asyncio

    from app.models import Project as ProjectModel

    async def _run() -> None:
        from app.main import engine
        from sqlalchemy.ext.asyncio import async_sessionmaker

        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            proj = await s.get(ProjectModel, project)
            if proj is None:
                return
        try:
            from app.worktree import delete_worktree
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, delete_worktree, ticket_id, proj.repo_path, worktree_path
            )
            logger.info("Deleted worktree for ticket %d: %s", ticket_id, worktree_path)
        except Exception as exc:
            logger.warning("Could not delete worktree for ticket %d: %s", ticket_id, exc)

    asyncio.create_task(_run(), name=f"delete-worktree-{ticket_id}")


@router.post("/complete/{ticket_id}", response_model=TicketResponse)
async def complete_ticket(
    ticket_id: int,
    session: AsyncSession = Depends(_get_session),
) -> Ticket:
    """Mark agent work as successful and advance ticket to next state."""
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.current_agent is None:
        raise HTTPException(
            status_code=400, detail="Ticket has no assigned agent"
        )

    previous_state = ticket.state
    next_state = COMPLETE_NEXT_STATE.get(previous_state)
    if next_state is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot complete ticket in state '{previous_state}'",
        )

    agent_id = ticket.current_agent
    worktree_path = ticket.worktree_path
    project = ticket.project
    ticket.previous_state = previous_state
    ticket.state = next_state

    # Release agent
    await _release_agent(session, ticket)

    await session.commit()
    await session.refresh(ticket)

    # Delete worktree once ticket is fully done (merger completed)
    if next_state == "done" and worktree_path:
        _delete_worktree_background(ticket_id, project, worktree_path)

    # Publish agent_completed event
    await publish_event(
        "ticket:events",
        {
            "event_type": "agent_completed",
            "ticket_id": ticket_id,
            "agent_id": agent_id,
            "previous_state": previous_state,
            "new_state": next_state,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )

    return ticket


@router.post("/fail/{ticket_id}", response_model=TicketResponse)
async def fail_ticket(
    ticket_id: int,
    payload: AgentFailRequest,
    session: AsyncSession = Depends(_get_session),
) -> Ticket:
    """Report agent task failure and return ticket to to_do."""
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.current_agent is None:
        raise HTTPException(
            status_code=400, detail="Ticket has no assigned agent"
        )

    agent_id = ticket.current_agent
    previous_state = ticket.state

    all_settings_result = await session.execute(select(Setting))
    db_overrides = {row.key: row.value for row in all_settings_result.scalars().all()}
    config = load_config(db_overrides=db_overrides)

    # Determine agent type from agent_id (format: "{type}-{hex}")
    agent_type = agent_id.rsplit("-", 1)[0] if "-" in agent_id else agent_id

    # Increment rejection/failure counters
    if agent_type == "developer":
        ticket.developer_failure_count += 1
    elif agent_type == "reviewer":
        ticket.review_rejection_count += 1
    elif agent_type == "tester":
        ticket.tester_rejection_count += 1

    # For reviewer rejections with structured feedback: append rework section
    # to the ticket description so the developer sees it prominently next pickup
    if agent_type == "reviewer" and payload.suggested_fixes:
        rejection_num = ticket.review_rejection_count
        rework_lines = [
            f"\n\n---",
            f"## Rework Required — Review #{rejection_num}",
            "",
        ]
        if payload.rework_note:
            rework_lines.append(payload.rework_note)
            rework_lines.append("")
        rework_lines.append("**Issues to address:**")
        for line in payload.suggested_fixes.splitlines():
            if line.strip():
                rework_lines.append(f"- {line.strip()}")
        rework_lines.append("")
        rework_lines.append(
            "_Most of the implementation is already in place. "
            "Address the issues above and resubmit._"
        )
        ticket.description = ticket.description + "\n".join(rework_lines)

    # For tester failures with structured feedback: append test failure section
    if agent_type == "tester" and payload.suggested_fixes:
        rejection_num = ticket.tester_rejection_count
        rework_lines = [
            f"\n\n---",
            f"## Test Failures — Attempt #{rejection_num}",
            "",
        ]
        if payload.rework_note:
            rework_lines.append(payload.rework_note)
            rework_lines.append("")
        rework_lines.append("**Failures to fix:**")
        for line in payload.suggested_fixes.splitlines():
            if line.strip():
                rework_lines.append(f"- {line.strip()}")
        rework_lines.append("")
        rework_lines.append(
            "_Fix the failing tests and unmet criteria above, then resubmit._"
        )
        ticket.description = ticket.description + "\n".join(rework_lines)

    # Add a summary note (visible in the ticket timeline)
    if agent_type == "reviewer" and payload.suggested_fixes:
        note_content = (
            f"Review #{ticket.review_rejection_count} rejected by {agent_id}.\n\n"
            f"**Summary:** {payload.reason}\n\n"
        )
        if payload.rework_note:
            note_content += f"{payload.rework_note}\n\n"
        note_content += f"**Issues:**\n{payload.suggested_fixes}"
        note_type = "review_rejection"
    elif agent_type == "tester" and payload.suggested_fixes:
        note_content = (
            f"Test run #{ticket.tester_rejection_count} failed by {agent_id}.\n\n"
            f"**Summary:** {payload.reason}\n\n"
        )
        if payload.rework_note:
            note_content += f"{payload.rework_note}\n\n"
        note_content += f"**Failures:**\n{payload.suggested_fixes}"
        note_type = "test_failure"
    else:
        note_content = f"Agent {agent_id} failed: {payload.reason}"
        note_type = "failure"

    note = Note(
        ticket_id=ticket_id,
        author=agent_id,
        content=note_content,
        note_type=note_type,
    )
    session.add(note)

    # Release agent
    await _release_agent(session, ticket)

    ticket.previous_state = previous_state

    # Merger failures always block — the agent already tried to resolve conflicts
    # and couldn't proceed; human intervention is required.
    if agent_type == "merger":
        ticket.state = "blocked"
        blocked_note = Note(
            ticket_id=ticket_id,
            author="system",
            content=(
                f"Ticket blocked: merger could not complete the merge.\n\n"
                f"**Reason:** {payload.reason}\n\n"
                "Manual intervention required."
            ),
            note_type="failure",
        )
        session.add(blocked_note)
    elif (
        agent_type == "developer"
        and ticket.developer_failure_count >= config.developer_failure_threshold
    ):
        ticket.state = "blocked"
        blocked_note = Note(
            ticket_id=ticket_id,
            author="system",
            content=(
                f"Ticket blocked: developer failed "
                f"{ticket.developer_failure_count} times "
                f"(threshold: {config.developer_failure_threshold}).\n\n"
                f"Last failure: {payload.reason}"
            ),
            note_type="failure",
        )
        session.add(blocked_note)
    elif (
        agent_type == "reviewer"
        and ticket.review_rejection_count >= config.review_rejection_threshold
    ):
        ticket.state = "blocked"
        blocked_note = Note(
            ticket_id=ticket_id,
            author="system",
            content=(
                f"Ticket blocked: review rejected "
                f"{ticket.review_rejection_count} times "
                f"(threshold: {config.review_rejection_threshold}).\n\n"
                f"Last failure: {payload.reason}"
            ),
            note_type="failure",
        )
        session.add(blocked_note)
    elif (
        agent_type == "tester"
        and ticket.tester_rejection_count >= config.tester_rejection_threshold
    ):
        ticket.state = "blocked"
        blocked_note = Note(
            ticket_id=ticket_id,
            author="system",
            content=(
                f"Ticket blocked: tester failed "
                f"{ticket.tester_rejection_count} times "
                f"(threshold: {config.tester_rejection_threshold}).\n\n"
                f"Last failure: {payload.reason}"
            ),
            note_type="failure",
        )
        session.add(blocked_note)
    else:
        ticket.state = "to_do"

    await session.commit()
    await session.refresh(ticket)

    # Publish event
    event_payload: dict[str, Any] = {
        "event_type": "agent_failed",
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "previous_state": previous_state,
        "new_state": ticket.state,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    await publish_event("ticket:events", event_payload)

    # If blocked, also publish ticket_blocked event
    if ticket.state == "blocked":
        blocked_payload: dict[str, Any] = {
            "event_type": "ticket_blocked",
            "ticket_id": ticket_id,
            "title": ticket.title,
            "project": ticket.project,
            "agent_id": agent_id,
            "review_rejection_count": ticket.review_rejection_count,
            "last_failure_note": note_content,
            "reason": payload.reason,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        await publish_event("ticket:events", blocked_payload)

    return ticket


async def check_agent_timeouts(
    session_factory: Any,
) -> None:
    """Check for agents that have exceeded their timeout and release them.

    This is designed to be called as a periodic background task.
    """
    from app.config import fetch_db_overrides, load_config as _load_config

    db = await fetch_db_overrides()
    config = _load_config(db_overrides=db)
    now = datetime.datetime.now(datetime.timezone.utc)

    async with session_factory() as session:
        # Find all busy agents
        result = await session.execute(
            select(AgentRegistry).where(AgentRegistry.status == "busy")
        )
        busy_agents = list(result.scalars().all())

        for agent_entry in busy_agents:
            if agent_entry.started_at is None or agent_entry.current_ticket_id is None:
                continue

            timeout_seconds = config.agent_timeouts.get(agent_entry.agent_type, 600)
            started = agent_entry.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=datetime.timezone.utc)
            elapsed = (now - started).total_seconds()

            if elapsed <= timeout_seconds:
                continue

            # Timed out — release agent and ticket
            ticket_result = await session.execute(
                select(Ticket).where(Ticket.id == agent_entry.current_ticket_id)
            )
            ticket = ticket_result.scalar_one_or_none()
            if ticket is None:
                continue

            previous_state = ticket.state
            agent_id = ticket.current_agent
            ticket.previous_state = previous_state

            # Check ralph.log for COMPLETE marker — ralph may have finished but
            # the result message was lost (e.g. backend restarted mid-spawn).
            ralph_completed = False
            if ticket.worktree_path:
                ralph_log = Path(ticket.worktree_path) / "ralph.log"
                try:
                    if ralph_log.exists():
                        content = ralph_log.read_text(errors="replace")
                        ralph_completed = "<promise>COMPLETE</promise>" in content
                except Exception:
                    pass

            if ralph_completed:
                # Ralph finished — advance the ticket rather than failing it.
                logger.info(
                    "Timeout recovery: ralph.log shows COMPLETE for ticket %d — completing",
                    ticket.id,
                )
                next_state = COMPLETE_NEXT_STATE.get(previous_state)
                if next_state:
                    ticket.state = next_state
                    ticket.current_agent = None
                    ticket.assigned_at = None
                    agent_entry.status = "available"
                    agent_entry.current_ticket_id = None
                    await session.commit()
                    await publish_event(
                        "ticket:events",
                        {
                            "event_type": "agent_completed",
                            "ticket_id": ticket.id,
                            "agent_id": agent_id,
                            "previous_state": previous_state,
                            "new_state": next_state,
                            "timestamp": now.isoformat(),
                        },
                    )
                continue

            # Ralph never ran or failed — increment counter and return/block.

            # Increment the correct timeout counter
            timeout_field = TIMEOUT_FIELD.get(agent_entry.agent_type)
            if timeout_field:
                current_val: int = getattr(ticket, timeout_field)
                setattr(ticket, timeout_field, current_val + 1)

            # Developer timeouts also count toward failure threshold
            if agent_entry.agent_type == "developer":
                ticket.developer_failure_count += 1

            # Determine next state — block if threshold reached, else return to to_do
            blocked_note: Note | None = None
            if (
                agent_entry.agent_type == "developer"
                and ticket.developer_failure_count >= config.developer_failure_threshold
            ):
                ticket.state = "blocked"
                blocked_note = Note(
                    ticket_id=ticket.id,
                    author="system",
                    content=(
                        f"Ticket blocked: developer failed (including timeouts) "
                        f"{ticket.developer_failure_count} times "
                        f"(threshold: {config.developer_failure_threshold}).\n\n"
                        "Last failure: timeout"
                    ),
                    note_type="failure",
                )
                session.add(blocked_note)
            else:
                ticket.state = "to_do"

            ticket.current_agent = None
            ticket.assigned_at = None

            # Update agent registry
            agent_entry.status = "available"
            agent_entry.current_ticket_id = None

            await session.commit()

            new_state = ticket.state
            await publish_event(
                "ticket:events",
                {
                    "event_type": "agent_failed",
                    "ticket_id": ticket.id,
                    "agent_id": agent_id,
                    "previous_state": previous_state,
                    "new_state": new_state,
                    "reason": "timeout",
                    "timestamp": now.isoformat(),
                },
            )
            if new_state == "blocked":
                await publish_event(
                    "ticket:events",
                    {
                        "event_type": "ticket_blocked",
                        "ticket_id": ticket.id,
                        "agent_id": agent_id,
                        "reason": "timeout threshold reached",
                        "timestamp": now.isoformat(),
                    },
                )
