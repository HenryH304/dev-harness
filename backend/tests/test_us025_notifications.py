"""Tests for US-025: Henry alert notifications for blocked tickets."""

import os
from unittest import mock

import pytest

from app.notifications import (
    NotificationAlert,
    build_alert,
    notification_listener,
    send_alert,
)


class TestBuildAlert:
    """Tests for building alert messages from ticket_blocked events."""

    def test_build_alert_with_all_fields(self) -> None:
        event: dict[str, object] = {
            "event_type": "ticket_blocked",
            "ticket_id": 42,
            "title": "Fix auth middleware",
            "project": "my-project",
            "review_rejection_count": 3,
            "last_failure_note": "Tests still failing on login endpoint",
            "agent_id": "reviewer-abc123",
            "timestamp": "2026-03-16T10:00:00+00:00",
        }
        alert = build_alert(event)
        assert alert.ticket_id == 42
        assert alert.title == "Fix auth middleware"
        assert alert.project == "my-project"
        assert alert.review_rejection_count == 3
        assert alert.last_failure_note == "Tests still failing on login endpoint"

    def test_build_alert_with_missing_optional_fields(self) -> None:
        event: dict[str, object] = {
            "event_type": "ticket_blocked",
            "ticket_id": 7,
        }
        alert = build_alert(event)
        assert alert.ticket_id == 7
        assert alert.title == "Unknown"
        assert alert.project == "Unknown"
        assert alert.review_rejection_count == 0
        assert alert.last_failure_note == ""

    def test_alert_message_format(self) -> None:
        alert = NotificationAlert(
            ticket_id=42,
            title="Fix auth middleware",
            project="my-project",
            review_rejection_count=3,
            last_failure_note="Tests failing",
        )
        message = alert.format_message()
        assert "Ticket #42" in message
        assert "Fix auth middleware" in message
        assert "my-project" in message
        assert "3" in message
        assert "Tests failing" in message


class TestSendAlert:
    """Tests for sending alerts (log file fallback)."""

    def test_send_alert_writes_to_log_file(self, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        log_path = str(tmp_path / "notifications.log")
        alert = NotificationAlert(
            ticket_id=42,
            title="Fix auth",
            project="proj",
            review_rejection_count=3,
            last_failure_note="Failing",
        )
        with mock.patch("app.notifications.NOTIFICATIONS_LOG_PATH", log_path):
            send_alert(alert)

        with open(log_path) as f:
            content = f.read()
        assert "Ticket #42" in content
        assert "Fix auth" in content

    def test_send_alert_appends_to_existing_log(self, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        log_path = str(tmp_path / "notifications.log")
        alert1 = NotificationAlert(
            ticket_id=1, title="A", project="p",
            review_rejection_count=3, last_failure_note="x",
        )
        alert2 = NotificationAlert(
            ticket_id=2, title="B", project="p",
            review_rejection_count=3, last_failure_note="y",
        )
        with mock.patch("app.notifications.NOTIFICATIONS_LOG_PATH", log_path):
            send_alert(alert1)
            send_alert(alert2)

        with open(log_path) as f:
            lines = f.readlines()
        # Should have at least 2 entries
        content = "".join(lines)
        assert "Ticket #1" in content
        assert "Ticket #2" in content

    def test_send_alert_creates_parent_directory(self, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        log_path = str(tmp_path / "subdir" / "notifications.log")
        alert = NotificationAlert(
            ticket_id=5, title="T", project="p",
            review_rejection_count=1, last_failure_note="n",
        )
        with mock.patch("app.notifications.NOTIFICATIONS_LOG_PATH", log_path):
            send_alert(alert)
        assert os.path.exists(log_path)


class TestNotificationListener:
    """Tests for the notification listener that subscribes to Redis events."""

    @pytest.mark.asyncio
    async def test_listener_processes_ticket_blocked_event(self) -> None:
        event = {
            "event_type": "ticket_blocked",
            "ticket_id": 42,
            "title": "Fix auth",
            "project": "proj",
            "review_rejection_count": 3,
            "last_failure_note": "Failing",
            "timestamp": "2026-03-16T10:00:00+00:00",
        }

        async def mock_subscribe(channel: str):  # type: ignore[no-untyped-def]
            yield event

        with (
            mock.patch(
                "app.notifications.subscribe_events", side_effect=mock_subscribe
            ),
            mock.patch("app.notifications.send_alert") as mock_send,
        ):
            await notification_listener()
            mock_send.assert_called_once()
            alert = mock_send.call_args[0][0]
            assert alert.ticket_id == 42

    @pytest.mark.asyncio
    async def test_listener_ignores_non_blocked_events(self) -> None:
        event = {
            "event_type": "ticket_state_changed",
            "ticket_id": 1,
            "timestamp": "2026-03-16T10:00:00+00:00",
        }

        async def mock_subscribe(channel: str):  # type: ignore[no-untyped-def]
            yield event

        with (
            mock.patch(
                "app.notifications.subscribe_events", side_effect=mock_subscribe
            ),
            mock.patch("app.notifications.send_alert") as mock_send,
        ):
            await notification_listener()
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_listener_enriches_event_from_db(self) -> None:
        """Listener should fetch ticket details if not in event payload."""
        event = {
            "event_type": "ticket_blocked",
            "ticket_id": 42,
            "review_rejection_count": 3,
            "reason": "Tests failing",
            "timestamp": "2026-03-16T10:00:00+00:00",
        }

        async def mock_subscribe(channel: str):  # type: ignore[no-untyped-def]
            yield event

        mock_ticket = mock.MagicMock()
        mock_ticket.title = "Fix auth"
        mock_ticket.project = "proj"

        mock_note = mock.MagicMock()
        mock_note.content = "Last failure details"

        async def mock_enrich(
            event: dict[str, object],
        ) -> dict[str, object]:
            return {
                **event,
                "title": "Fix auth",
                "project": "proj",
                "last_failure_note": "Last failure details",
            }

        with (
            mock.patch(
                "app.notifications.subscribe_events", side_effect=mock_subscribe
            ),
            mock.patch(
                "app.notifications.enrich_event", side_effect=mock_enrich
            ),
            mock.patch("app.notifications.send_alert") as mock_send,
        ):
            await notification_listener()
            mock_send.assert_called_once()
            alert = mock_send.call_args[0][0]
            assert alert.title == "Fix auth"
            assert alert.project == "proj"
            assert alert.last_failure_note == "Last failure details"


class TestEnrichEvent:
    """Tests for enriching blocked events with ticket data from DB."""

    @pytest.mark.asyncio
    async def test_enrich_adds_ticket_details(self) -> None:
        from app.notifications import enrich_event

        event: dict[str, object] = {
            "event_type": "ticket_blocked",
            "ticket_id": 42,
            "review_rejection_count": 3,
        }

        mock_ticket = mock.MagicMock()
        mock_ticket.title = "Fix auth"
        mock_ticket.project = "proj"

        mock_note = mock.MagicMock()
        mock_note.content = "Agent failed: tests broken"

        # Mock the session and query
        mock_session = mock.AsyncMock()
        # First execute: ticket query
        mock_ticket_result = mock.MagicMock()
        mock_ticket_result.scalar_one_or_none.return_value = mock_ticket
        # Second execute: note query
        mock_note_result = mock.MagicMock()
        mock_note_result.scalar_one_or_none.return_value = mock_note

        mock_session.execute = mock.AsyncMock(
            side_effect=[mock_ticket_result, mock_note_result]
        )

        mock_session_factory = mock.MagicMock()
        mock_session_factory.return_value.__aenter__ = mock.AsyncMock(
            return_value=mock_session
        )
        mock_session_factory.return_value.__aexit__ = mock.AsyncMock(
            return_value=False
        )

        with mock.patch(
            "app.notifications._get_session_factory",
            return_value=mock_session_factory,
        ):
            enriched = await enrich_event(event)

        assert enriched["title"] == "Fix auth"
        assert enriched["project"] == "proj"
        assert enriched["last_failure_note"] == "Agent failed: tests broken"

    @pytest.mark.asyncio
    async def test_enrich_returns_event_unchanged_if_db_fails(self) -> None:
        from app.notifications import enrich_event

        event: dict[str, object] = {
            "event_type": "ticket_blocked",
            "ticket_id": 42,
        }

        with mock.patch(
            "app.notifications._get_session_factory",
            side_effect=Exception("DB unavailable"),
        ):
            enriched = await enrich_event(event)

        # Should return event as-is
        assert enriched == event
