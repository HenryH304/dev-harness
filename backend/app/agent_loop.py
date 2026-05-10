"""Autonomous agent loop — picks up tickets and runs ralph when triggered.

Three-layer strategy:
  1. Event-driven: Redis ticket:events triggers immediate pickup when a ticket
     lands in an agent's input column.
  2. Startup scan: on server start, sweep all input columns for waiting tickets.
  3. Heartbeat: every 5 minutes, sweep again to catch any missed events.
"""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import AGENT_TYPES
from app.models import Note
from app.schemas import AgentFailRequest

logger = logging.getLogger(__name__)

# Maps a ticket's waiting state to the agent type that handles it
STATE_TO_AGENT: dict[str, str] = {
    "to_do": "developer",
    "ready_for_review": "reviewer",
    "ready_for_test": "tester",
    "ready_to_merge": "merger",
}

_HEARTBEAT_INTERVAL = 300  # 5 minutes


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    from app.main import engine

    return async_sessionmaker(engine, expire_on_commit=False)


async def try_pickup_and_run(agent_type: str) -> None:
    """Pick up one ticket for agent_type and run ralph on it.

    Silently returns on expected empty/capacity conditions (404, 409, 429).
    Logs and returns on unexpected errors so the caller's task survives.
    """
    from fastapi import HTTPException

    from app.ralph_runner import spawn_agent
    from app.routers.agents import complete_ticket, fail_ticket, pickup_ticket

    session_factory = _get_session_factory()

    # ── Step 1: pickup ─────────────────────────────────────────────────────
    ticket_id: int | None = None
    ticket_dict: dict[str, Any] = {}
    notes: list[dict[str, str]] = []

    try:
        async with session_factory() as session:
            try:
                ticket = await pickup_ticket(agent_type, session=session)
            except HTTPException as exc:
                if exc.status_code not in (404, 409, 429):
                    logger.error("Pickup error for %s: %s", agent_type, exc.detail)
                return

            ticket_id = ticket.id
            ticket_dict = {
                "id": ticket.id,
                "project": ticket.project,
                "title": ticket.title,
                "description": ticket.description,
                "acceptance_criteria": ticket.acceptance_criteria,
                "priority": ticket.priority,
                "worktree_path": ticket.worktree_path,
                "branch_name": ticket.branch_name,
            }

            note_result = await session.execute(
                select(Note)
                .where(Note.ticket_id == ticket.id)
                .order_by(Note.created_at.asc())
            )
            notes = [
                {"author": n.author, "content": n.content, "note_type": n.note_type}
                for n in note_result.scalars().all()
            ]
    except Exception as exc:
        logger.error("Unexpected pickup error for %s: %s", agent_type, exc)
        return

    if ticket_id is None:
        return

    logger.info("Agent loop: %s picked up ticket %d", agent_type, ticket_id)

    # ── Step 2: run ralph ──────────────────────────────────────────────────
    try:
        spawn_result = await spawn_agent(ticket_dict, agent_type, notes)
    except ValueError as exc:
        logger.error("Spawn failed for ticket %d: %s", ticket_id, exc)
        async with session_factory() as session:
            try:
                await fail_ticket(
                    ticket_id,
                    AgentFailRequest(reason=f"Spawn error: {exc}"),
                    session=session,
                )
            except Exception:
                pass
        return

    logger.info(
        "Agent loop: %s finished ticket %d (exit_code=%d)",
        agent_type,
        ticket_id,
        spawn_result.exit_code,
    )

    # ── Step 3: report result ──────────────────────────────────────────────
    async with session_factory() as session:
        try:
            if spawn_result.success:
                await complete_ticket(ticket_id, session=session)
            else:
                await fail_ticket(
                    ticket_id,
                    AgentFailRequest(
                        reason=f"ralph exited with code {spawn_result.exit_code}"
                    ),
                    session=session,
                )
        except HTTPException as exc:
            logger.error("Result report failed for ticket %d: %s", ticket_id, exc.detail)
        except Exception as exc:
            logger.error("Unexpected result report error for ticket %d: %s", ticket_id, exc)


def _schedule_pickup(agent_type: str) -> None:
    """Fire-and-forget: create an asyncio task for a pickup+run."""
    asyncio.create_task(
        try_pickup_and_run(agent_type),
        name=f"pickup-{agent_type}",
    )


async def agent_event_listener() -> None:
    """Continuously subscribe to Redis ticket:events and trigger pickups.

    Triggers on:
      - ticket_state_changed  → new_state maps to an agent's input column
      - agent_failed          → ticket returns to to_do, developer needed
      - developer_work_available → batch import just created new to_do tickets
    """
    from app.redis_client import get_redis

    client = await get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe("ticket:events")
    logger.info("Agent event listener started")

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.05)
                continue

            try:
                event = json.loads(message["data"])
            except Exception:
                continue

            event_type = event.get("event_type", "")
            new_state: str = event.get("new_state", "")

            if event_type == "developer_work_available":
                _schedule_pickup("developer")
                continue

            if event_type in ("ticket_state_changed", "agent_failed"):
                agent_type = STATE_TO_AGENT.get(new_state)
                if agent_type:
                    _schedule_pickup(agent_type)

    finally:
        await pubsub.unsubscribe("ticket:events")


async def startup_scan() -> None:
    """Sweep all input columns for waiting tickets on server start."""
    await asyncio.sleep(2)  # let the server finish initialising
    logger.info("Agent loop: running startup scan")
    for agent_type in AGENT_TYPES:
        _schedule_pickup(agent_type)


async def heartbeat_loop() -> None:
    """Every 5 minutes, sweep all input columns to catch missed events."""
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        logger.debug("Agent loop: heartbeat scan")
        for agent_type in AGENT_TYPES:
            _schedule_pickup(agent_type)
