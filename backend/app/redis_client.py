"""Redis client for event publishing."""

import json
import os
from typing import Any

import redis.asyncio as redis

_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get or create a Redis client."""
    global _redis_client  # noqa: PLW0603
    if _redis_client is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis_client = redis.from_url(redis_url)  # type: ignore[no-untyped-call]
    return _redis_client


async def publish_event(channel: str, event: dict[str, Any]) -> None:
    """Publish a JSON event to a Redis channel."""
    client = await get_redis()
    await client.publish(channel, json.dumps(event))


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis_client  # noqa: PLW0603
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
