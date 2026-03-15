"""Tests for US-008: Redis event publisher and subscriber."""

import datetime
import json
from typing import Any
from unittest import mock

import pytest

from app.redis_client import (
    EVENT_TYPES,
    close_redis,
    create_event_payload,
    get_redis,
    publish_event,
    subscribe_events,
)


class TestEventTypes:
    """Test that all required event types are defined."""

    def test_ticket_state_changed_in_event_types(self) -> None:
        assert "ticket_state_changed" in EVENT_TYPES

    def test_agent_assigned_in_event_types(self) -> None:
        assert "agent_assigned" in EVENT_TYPES

    def test_agent_completed_in_event_types(self) -> None:
        assert "agent_completed" in EVENT_TYPES

    def test_agent_failed_in_event_types(self) -> None:
        assert "agent_failed" in EVENT_TYPES

    def test_ticket_blocked_in_event_types(self) -> None:
        assert "ticket_blocked" in EVENT_TYPES


class TestCreateEventPayload:
    """Test event payload creation."""

    def test_payload_includes_event_type(self) -> None:
        payload = create_event_payload(
            event_type="ticket_state_changed",
            ticket_id=1,
        )
        assert payload["event_type"] == "ticket_state_changed"

    def test_payload_includes_ticket_id(self) -> None:
        payload = create_event_payload(
            event_type="agent_assigned",
            ticket_id=42,
        )
        assert payload["ticket_id"] == 42

    def test_payload_includes_timestamp(self) -> None:
        payload = create_event_payload(
            event_type="ticket_state_changed",
            ticket_id=1,
        )
        assert "timestamp" in payload
        # Should be a valid ISO format string
        datetime.datetime.fromisoformat(payload["timestamp"])

    def test_payload_includes_optional_fields(self) -> None:
        payload = create_event_payload(
            event_type="ticket_state_changed",
            ticket_id=1,
            previous_state="to_do",
            new_state="in_progress",
            agent_id="dev-001",
        )
        assert payload["previous_state"] == "to_do"
        assert payload["new_state"] == "in_progress"
        assert payload["agent_id"] == "dev-001"

    def test_payload_omits_none_optional_fields(self) -> None:
        payload = create_event_payload(
            event_type="ticket_state_changed",
            ticket_id=1,
        )
        assert "previous_state" not in payload
        assert "new_state" not in payload
        assert "agent_id" not in payload

    def test_payload_is_json_serializable(self) -> None:
        payload = create_event_payload(
            event_type="ticket_state_changed",
            ticket_id=1,
            previous_state="to_do",
            new_state="in_progress",
            agent_id="dev-001",
        )
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)
        assert deserialized == payload


class TestGetRedis:
    """Test Redis client initialization."""

    @pytest.fixture(autouse=True)
    async def _reset_redis(self) -> Any:
        """Reset redis client between tests."""
        yield
        await close_redis()

    async def test_get_redis_returns_client(self) -> None:
        with mock.patch("app.redis_client.redis") as mock_redis:
            mock_client = mock.AsyncMock()
            mock_redis.from_url.return_value = mock_client
            client = await get_redis()
            assert client is mock_client

    async def test_get_redis_uses_env_url(self) -> None:
        with (
            mock.patch("app.redis_client.redis") as mock_redis,
            mock.patch.dict("os.environ", {"REDIS_URL": "redis://custom:1234"}),
        ):
            mock_redis.from_url.return_value = mock.AsyncMock()
            # Reset to force re-creation
            import app.redis_client

            app.redis_client._redis_client = None
            await get_redis()
            mock_redis.from_url.assert_called_with("redis://custom:1234")

    async def test_get_redis_singleton(self) -> None:
        with mock.patch("app.redis_client.redis") as mock_redis:
            mock_client = mock.AsyncMock()
            mock_redis.from_url.return_value = mock_client
            import app.redis_client

            app.redis_client._redis_client = None
            client1 = await get_redis()
            client2 = await get_redis()
            assert client1 is client2
            # Should only create once
            mock_redis.from_url.assert_called_once()


class TestPublishEvent:
    """Test event publishing."""

    @pytest.fixture(autouse=True)
    async def _reset_redis(self) -> Any:
        """Reset redis client between tests."""
        yield
        await close_redis()

    async def test_publish_event_calls_redis_publish(self) -> None:
        mock_client = mock.AsyncMock()
        with mock.patch("app.redis_client.get_redis", return_value=mock_client):
            event = {"event_type": "ticket_state_changed", "ticket_id": 1}
            await publish_event("ticket:events", event)
            mock_client.publish.assert_called_once_with(
                "ticket:events", json.dumps(event)
            )

    async def test_publish_event_serializes_to_json(self) -> None:
        mock_client = mock.AsyncMock()
        with mock.patch("app.redis_client.get_redis", return_value=mock_client):
            event = {
                "event_type": "ticket_state_changed",
                "ticket_id": 1,
                "timestamp": "2026-03-15T12:00:00+00:00",
            }
            await publish_event("ticket:events", event)
            published_data = mock_client.publish.call_args[0][1]
            parsed = json.loads(published_data)
            assert parsed == event

    async def test_publish_to_custom_channel(self) -> None:
        mock_client = mock.AsyncMock()
        with mock.patch("app.redis_client.get_redis", return_value=mock_client):
            await publish_event("custom:channel", {"event_type": "test"})
            assert mock_client.publish.call_args[0][0] == "custom:channel"


class TestSubscribeEvents:
    """Test event subscription."""

    async def test_subscribe_events_yields_events(self) -> None:
        """Test that subscribe_events yields parsed JSON events."""
        mock_pubsub = mock.AsyncMock()
        mock_message = {
            "type": "message",
            "data": json.dumps(
                {"event_type": "ticket_state_changed", "ticket_id": 1}
            ).encode(),
        }

        call_count = 0

        async def mock_get_message(
            ignore_subscribe_messages: bool = True, timeout: float = 1.0
        ) -> dict[str, Any] | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_message
            # Return None to signal no more messages
            return None

        mock_pubsub.get_message = mock_get_message
        mock_pubsub.subscribe = mock.AsyncMock()
        mock_pubsub.unsubscribe = mock.AsyncMock()

        mock_client = mock.AsyncMock()
        mock_client.pubsub = mock.MagicMock(return_value=mock_pubsub)

        events: list[dict[str, Any]] = []
        with mock.patch("app.redis_client.get_redis", return_value=mock_client):
            async for event in subscribe_events("ticket:events"):
                events.append(event)
                break  # Stop after first event

        assert len(events) == 1
        assert events[0]["event_type"] == "ticket_state_changed"
        assert events[0]["ticket_id"] == 1

    async def test_subscribe_events_subscribes_to_channel(self) -> None:
        """Test that subscribe subscribes to the correct channel."""
        mock_pubsub = mock.AsyncMock()

        async def mock_get_message(
            ignore_subscribe_messages: bool = True, timeout: float = 1.0
        ) -> None:
            return None

        mock_pubsub.get_message = mock_get_message
        mock_pubsub.subscribe = mock.AsyncMock()
        mock_pubsub.unsubscribe = mock.AsyncMock()

        mock_client = mock.AsyncMock()
        mock_client.pubsub = mock.MagicMock(return_value=mock_pubsub)

        with mock.patch("app.redis_client.get_redis", return_value=mock_client):
            async for _ in subscribe_events("ticket:events"):
                break

        mock_pubsub.subscribe.assert_called_once_with("ticket:events")

    async def test_subscribe_events_skips_non_message_types(self) -> None:
        """Test that subscribe skips non-message type events."""
        mock_pubsub = mock.AsyncMock()
        call_count = 0

        async def mock_get_message(
            ignore_subscribe_messages: bool = True, timeout: float = 1.0
        ) -> dict[str, Any] | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # A subscribe confirmation — should be skipped
                return {"type": "subscribe", "data": 1}
            if call_count == 2:
                return {
                    "type": "message",
                    "data": json.dumps({"event_type": "test"}).encode(),
                }
            return None

        mock_pubsub.get_message = mock_get_message
        mock_pubsub.subscribe = mock.AsyncMock()
        mock_pubsub.unsubscribe = mock.AsyncMock()

        mock_client = mock.AsyncMock()
        mock_client.pubsub = mock.MagicMock(return_value=mock_pubsub)

        events: list[dict[str, Any]] = []
        with mock.patch("app.redis_client.get_redis", return_value=mock_client):
            async for event in subscribe_events("ticket:events"):
                events.append(event)
                break

        assert len(events) == 1
        assert events[0]["event_type"] == "test"

    async def test_subscribe_events_unsubscribes_on_break(self) -> None:
        """Test that breaking out of the generator cleans up."""
        mock_pubsub = mock.AsyncMock()

        async def mock_get_message(
            ignore_subscribe_messages: bool = True, timeout: float = 1.0
        ) -> dict[str, Any]:
            return {
                "type": "message",
                "data": json.dumps({"event_type": "test"}).encode(),
            }

        mock_pubsub.get_message = mock_get_message
        mock_pubsub.subscribe = mock.AsyncMock()
        mock_pubsub.unsubscribe = mock.AsyncMock()

        mock_client = mock.AsyncMock()
        mock_client.pubsub = mock.MagicMock(return_value=mock_pubsub)

        with mock.patch("app.redis_client.get_redis", return_value=mock_client):
            gen = subscribe_events("ticket:events")
            async for _ in gen:
                break
            # Explicitly close generator to trigger finally block
            await gen.aclose()

        mock_pubsub.unsubscribe.assert_called_once_with("ticket:events")


class TestCloseRedis:
    """Test Redis cleanup."""

    async def test_close_redis_closes_client(self) -> None:
        import app.redis_client

        mock_client = mock.AsyncMock()
        app.redis_client._redis_client = mock_client
        await close_redis()
        mock_client.aclose.assert_called_once()
        assert app.redis_client._redis_client is None

    async def test_close_redis_noop_when_no_client(self) -> None:
        import app.redis_client

        app.redis_client._redis_client = None
        await close_redis()  # Should not raise


class TestRedisLifespan:
    """Test that Redis is initialized and cleaned up with FastAPI lifespan."""

    async def test_lifespan_closes_redis(self) -> None:
        """Test that lifespan handler closes Redis on shutdown."""
        from app.main import app, lifespan

        with (
            mock.patch("app.main.close_redis", new_callable=mock.AsyncMock) as mock_close,
            mock.patch("app.main.init_db", new_callable=mock.AsyncMock),
        ):
            async with lifespan(app):
                pass
            mock_close.assert_called_once()
