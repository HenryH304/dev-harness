"""Notification service for blocked ticket alerts.

Subscribes to ticket_blocked events on Redis and sends alerts
(logs to file as fallback when OpenClaw is not available).
"""

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Note, Ticket
from app.redis_client import subscribe_events

# Default path for notification log file (fallback when OpenClaw unavailable)
NOTIFICATIONS_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "notifications.log",
)


@dataclass
class NotificationAlert:
    """Alert data for a blocked ticket notification."""

    ticket_id: int
    title: str
    project: str
    review_rejection_count: int
    last_failure_note: str

    def format_message(self) -> str:
        """Format the alert as a human-readable message."""
        lines = [
            f"[BLOCKED] Ticket #{self.ticket_id}: {self.title}",
            f"  Project: {self.project}",
            f"  Review rejections: {self.review_rejection_count}",
            f"  Last failure: {self.last_failure_note}",
        ]
        return "\n".join(lines)


def build_alert(event: dict[str, Any]) -> NotificationAlert:
    """Build a NotificationAlert from a ticket_blocked event payload."""
    return NotificationAlert(
        ticket_id=int(event.get("ticket_id", 0)),
        title=str(event.get("title", "Unknown")),
        project=str(event.get("project", "Unknown")),
        review_rejection_count=int(event.get("review_rejection_count", 0)),
        last_failure_note=str(event.get("last_failure_note", "")),
    )


def send_alert(alert: NotificationAlert) -> None:
    """Send a blocked ticket alert.

    Logs to a notifications file (fallback when OpenClaw is not available).
    """
    log_path = NOTIFICATIONS_LOG_PATH
    parent = Path(log_path).parent
    parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry = f"[{timestamp}] {alert.format_message()}\n\n"

    with open(log_path, "a") as f:
        f.write(entry)


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get a session factory from the app engine."""
    from app.main import engine

    return async_sessionmaker(engine, expire_on_commit=False)


async def enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    """Enrich a ticket_blocked event with ticket details from the database.

    Fetches title, project, and last failure note if not already in the event.
    Returns the event unchanged if the database is unavailable.
    """
    try:
        session_factory = _get_session_factory()
        async with session_factory() as session:
            # Fetch ticket details
            ticket_id = int(event.get("ticket_id", 0))
            result = await session.execute(
                select(Ticket).where(Ticket.id == ticket_id)
            )
            ticket = result.scalar_one_or_none()
            if ticket is not None:
                event = {**event}
                if "title" not in event:
                    event["title"] = ticket.title
                if "project" not in event:
                    event["project"] = ticket.project

            # Fetch last failure note
            if "last_failure_note" not in event:
                note_result = await session.execute(
                    select(Note)
                    .where(Note.ticket_id == ticket_id, Note.note_type == "failure")
                    .order_by(Note.id.desc())
                    .limit(1)
                )
                note = note_result.scalar_one_or_none()
                if note is not None:
                    event = {**event, "last_failure_note": note.content}
    except Exception:
        # DB unavailable — return event as-is
        pass

    return event


async def notification_listener() -> None:
    """Listen for ticket_blocked events and send alerts.

    Subscribes to Redis ticket:events channel and filters for
    ticket_blocked events. Enriches events with DB data and sends alerts.
    """
    async for event in subscribe_events("ticket:events"):
        if event.get("event_type") != "ticket_blocked":
            continue

        # Enrich with ticket details from DB
        enriched = await enrich_event(event)
        alert = build_alert(enriched)
        send_alert(alert)
