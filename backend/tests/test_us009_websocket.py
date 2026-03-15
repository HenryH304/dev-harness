"""Tests for US-009: WebSocket endpoint for real-time board updates."""

import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.websocket import ConnectionManager

# --- ConnectionManager unit tests ---


class TestConnectionManager:
    """Tests for the WebSocket connection manager."""

    def test_manager_starts_empty(self) -> None:
        manager = ConnectionManager()
        assert manager.active_connections == []

    @pytest.mark.asyncio
    async def test_connect_adds_connection(self) -> None:
        manager = ConnectionManager()
        ws = mock.AsyncMock()
        await manager.connect(ws)
        assert ws in manager.active_connections
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self) -> None:
        manager = ConnectionManager()
        ws = mock.AsyncMock()
        await manager.connect(ws)
        manager.disconnect(ws)
        assert ws not in manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_unknown_connection_no_error(self) -> None:
        manager = ConnectionManager()
        ws = mock.AsyncMock()
        # Should not raise even if not connected
        manager.disconnect(ws)
        assert manager.active_connections == []

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self) -> None:
        manager = ConnectionManager()
        ws1 = mock.AsyncMock()
        ws2 = mock.AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)

        message = {"event_type": "ticket_state_changed", "ticket_id": 1}
        await manager.broadcast(message)

        expected = json.dumps(message)
        ws1.send_text.assert_awaited_once_with(expected)
        ws2.send_text.assert_awaited_once_with(expected)

    @pytest.mark.asyncio
    async def test_broadcast_removes_stale_connections(self) -> None:
        manager = ConnectionManager()
        ws_good = mock.AsyncMock()
        ws_stale = mock.AsyncMock()
        ws_stale.send_text.side_effect = Exception("connection closed")
        await manager.connect(ws_good)
        await manager.connect(ws_stale)

        message = {"event_type": "test"}
        await manager.broadcast(message)

        # Stale connection should be removed
        assert ws_stale not in manager.active_connections
        assert ws_good in manager.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_empty_connections(self) -> None:
        manager = ConnectionManager()
        # Should not raise
        await manager.broadcast({"event_type": "test"})

    @pytest.mark.asyncio
    async def test_connection_count(self) -> None:
        manager = ConnectionManager()
        ws1 = mock.AsyncMock()
        ws2 = mock.AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)
        assert len(manager.active_connections) == 2
        manager.disconnect(ws1)
        assert len(manager.active_connections) == 1


# --- WebSocket endpoint integration tests ---


class TestWebSocketEndpoint:
    """Tests for the /ws WebSocket endpoint."""

    def test_websocket_accepts_connection(self) -> None:
        client = TestClient(app)
        with mock.patch("app.main.init_db"), mock.patch("app.main.close_redis"):
            with client.websocket_connect("/ws") as websocket:
                # Connection established successfully
                websocket.send_text("ping")
                # Just verify connection works - close gracefully
                websocket.close()

    def test_websocket_receives_broadcast(self) -> None:
        client = TestClient(app)
        with mock.patch("app.main.init_db"), mock.patch("app.main.close_redis"):
            with client.websocket_connect("/ws") as websocket:
                # Import the manager used by the app
                from app.websocket import manager

                # Broadcast a message via the manager directly
                event = {
                    "event_type": "ticket_state_changed",
                    "ticket_id": 1,
                    "previous_state": "to_do",
                    "new_state": "in_progress",
                }
                # Run broadcast in the event loop
                import asyncio

                loop = asyncio.get_event_loop()
                loop.run_until_complete(manager.broadcast(event))

                data = websocket.receive_json()
                assert data["event_type"] == "ticket_state_changed"
                assert data["ticket_id"] == 1
                websocket.close()

    def test_websocket_multiple_clients(self) -> None:
        client = TestClient(app)
        with mock.patch("app.main.init_db"), mock.patch("app.main.close_redis"):
            with client.websocket_connect("/ws") as ws1:
                with client.websocket_connect("/ws") as ws2:
                    from app.websocket import manager

                    event = {"event_type": "test", "ticket_id": 42}
                    import asyncio

                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(manager.broadcast(event))

                    data1 = ws1.receive_json()
                    data2 = ws2.receive_json()
                    assert data1["ticket_id"] == 42
                    assert data2["ticket_id"] == 42
                    ws1.close()
                    ws2.close()

    def test_websocket_disconnect_cleanup(self) -> None:
        client = TestClient(app)
        with mock.patch("app.main.init_db"), mock.patch("app.main.close_redis"):
            from app.websocket import manager

            initial_count = len(manager.active_connections)
            with client.websocket_connect("/ws") as websocket:
                assert len(manager.active_connections) == initial_count + 1
                websocket.close()
            # After close, connection should be cleaned up
            assert len(manager.active_connections) == initial_count


# --- Redis subscriber broadcast tests ---


class TestRedisSubscriberBroadcast:
    """Tests for the Redis subscriber that broadcasts to WebSocket clients."""

    @pytest.mark.asyncio
    async def test_redis_listener_broadcasts_events(self) -> None:
        """Test that Redis events are forwarded to WebSocket clients."""
        from app.websocket import ConnectionManager, redis_listener

        mgr = ConnectionManager()
        ws = mock.AsyncMock()
        await mgr.connect(ws)

        event_data = {
            "event_type": "ticket_state_changed",
            "ticket_id": 1,
            "previous_state": "to_do",
            "new_state": "in_progress",
        }

        # Mock subscribe_events to yield one event then stop
        async def fake_subscribe(channel: str):  # type: ignore[no-untyped-def]
            yield event_data

        with mock.patch("app.websocket.subscribe_events", fake_subscribe):
            await redis_listener(mgr)

        ws.send_text.assert_awaited_once_with(json.dumps(event_data))

    @pytest.mark.asyncio
    async def test_redis_listener_handles_subscribe_error(self) -> None:
        """Test that redis_listener handles subscription errors gracefully."""
        from app.websocket import ConnectionManager, redis_listener

        mgr = ConnectionManager()

        async def failing_subscribe(channel: str):  # type: ignore[no-untyped-def]
            raise ConnectionError("Redis unavailable")
            yield  # type: ignore[misc]  # make it a generator

        with mock.patch("app.websocket.subscribe_events", failing_subscribe):
            # Should not raise - handles error gracefully
            await redis_listener(mgr)

    @pytest.mark.asyncio
    async def test_redis_listener_uses_correct_channel(self) -> None:
        """Test that redis_listener subscribes to ticket:events channel."""
        from app.websocket import ConnectionManager, redis_listener

        mgr = ConnectionManager()

        subscribe_mock = mock.MagicMock()

        async def capture_subscribe(channel: str):  # type: ignore[no-untyped-def]
            subscribe_mock(channel)
            return
            yield  # type: ignore[misc]  # make it a generator

        with mock.patch("app.websocket.subscribe_events", capture_subscribe):
            await redis_listener(mgr)

        subscribe_mock.assert_called_once_with("ticket:events")
