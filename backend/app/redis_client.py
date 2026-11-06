"""Redis client for event publishing and subscribing."""

import datetime
import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as redis

_redis_client: redis.Redis | None = None

# All supported event types
EVENT_TYPES: set[str] = {
    "ticket_state_changed",
    "agent_assigned",
    "agent_completed",
    "agent_failed",
    "ticket_blocked",
    "spec_update",
    "developer_work_available",
}


async def get_redis() -> redis.Redis:
    """Get or create a Redis client."""
    global _redis_client  # noqa: PLW0603
    if _redis_client is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis_client = redis.from_url(redis_url)  # type: ignore[no-untyped-call]
    return _redis_client


def create_event_payload(
    *,
    event_type: str,
    ticket_id: int,
    previous_state: str | None = None,
    new_state: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Create a standardized event payload."""
    payload: dict[str, Any] = {
        "event_type": event_type,
        "ticket_id": ticket_id,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if previous_state is not None:
        payload["previous_state"] = previous_state
    if new_state is not None:
        payload["new_state"] = new_state
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return payload


async def publish_event(channel: str, event: dict[str, Any]) -> None:
    """Publish a JSON event to a Redis channel."""
    client = await get_redis()
    await client.publish(channel, json.dumps(event))


async def subscribe_events(channel: str) -> AsyncGenerator[dict[str, Any], None]:
    """Subscribe to a Redis channel and yield parsed JSON events.

    Usage:
        async for event in subscribe_events("ticket:events"):
            print(event)
    """
    client = await get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                continue
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            yield data
    finally:
        await pubsub.unsubscribe(channel)


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis_client  # noqa: PLW0603
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
