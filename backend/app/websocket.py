"""WebSocket connection manager and Redis event broadcaster."""

import json
import logging
from typing import Any

from fastapi import WebSocket

from app.redis_client import subscribe_events

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and track a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from tracking."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients, removing stale ones."""
        stale: list[WebSocket] = []
        data = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except Exception:
                stale.append(connection)
        for conn in stale:
            self.disconnect(conn)


# Global manager instance
manager = ConnectionManager()


async def redis_listener(mgr: ConnectionManager | None = None) -> None:
    """Subscribe to Redis ticket:events and broadcast to WebSocket clients."""
    target = mgr or manager
    try:
        async for event in subscribe_events("ticket:events"):
            await target.broadcast(event)
    except Exception:
        logger.warning("Redis listener error, will retry on next connection")
