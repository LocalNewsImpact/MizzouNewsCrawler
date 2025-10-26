"""Tests for content cleaning telemetry system."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from src.utils.content_cleaning_telemetry import ContentCleaningTelemetry


class InMemoryStore:
    """Telemetry store backed by a single in-memory SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.submitted: list[Callable[[sqlite3.Connection], None]] = []

    def submit(self, writer: Callable[[sqlite3.Connection], None]) -> None:
        self.submitted.append(writer)

    def flush(self) -> None:
        while self.submitted:
            writer = self.submitted.pop(0)
            writer(self._conn)
        self._conn.commit()

    class _ConnectionContext:
        def __init__(self, store: InMemoryStore) -> None:
            self._store = store

        def __enter__(self) -> sqlite3.Connection:
            return self._store._conn

        def __exit__(
            self,
            exc_type,
            exc: Exception | None,
            exc_tb,
        ) -> None:
            self._store._conn.commit()

    def connection(self) -> InMemoryStore._ConnectionContext:
        return InMemoryStore._ConnectionContext(self)


@pytest.fixture
def mock_store():
    """Create a mock telemetry store."""
    store = Mock()
    store.submit = Mock()
    store.flush = Mock()

    # Mock connection context manager
    mock_conn = Mock(spec=sqlite3.Connection)
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.close.return_value = None

    # Create proper context manager mock
    mock_context_manager = Mock()
    mock_context_manager.__enter__ = Mock(return_value=mock_conn)
    mock_context_manager.__exit__ = Mock(return_value=None)
    store.connection.return_value = mock_context_manager

    return store


@pytest.fixture
def telemetry(mock_store):
    """Create content cleaning telemetry instance with mocked store."""
    return ContentCleaningTelemetry(
        enable_telemetry=True, store=mock_store, database_url="test://db"
    )


@pytest.fixture
def disabled_telemetry():
    """Create disabled telemetry instance."""
    return ContentCleaningTelemetry(enable_telemetry=False)


@pytest.fixture
def telemetry_store() -> Iterator[tuple[InMemoryStore, sqlite3.Connection]]:
    """Provide an in-memory telemetry store and connection."""
    conn = sqlite3.connect(":memory:")
    store = InMemoryStore(conn)
    try:
        yield store, conn
    finally:
        conn.close()


class TestContentCleaningTelemetryInit:
    """Tests for ContentCleaningTelemetry initialization."""

    def test_init_with_telemetry_enabled(self, mock_store):
        """Should initialize with telemetry enabled and create session ID."""
        telemetry = ContentCleaningTelemetry(enable_telemetry=True, store=mock_store)

        assert telemetry.enable_telemetry is True
        assert telemetry.session_id is not None
        assert telemetry.detection_counter == 0
        assert telemetry._store == mock_store
        assert telemetry.current_session is None
        assert telemetry.detected_segments == []
        assert telemetry.wire_detection_events == []
        assert telemetry.locality_detection_events == []

    def test_init_with_telemetry_disabled(self):
        """Should initialize with telemetry disabled."""
        telemetry = ContentCleaningTelemetry(enable_telemetry=False)

        assert telemetry.enable_telemetry is False
        assert telemetry.session_id is not None

    @patch("src.utils.content_cleaning_telemetry.get_store")
    def test_init_creates_default_store(self, mock_get_store):
        """Should create default store when none provided (lazy loading)."""
        mock_store = Mock()
        mock_get_store.return_value = mock_store

        telemetry = ContentCleaningTelemetry(database_url="test://custom_db")

        # Store is lazy-loaded, so access it to trigger get_store call
        _ = telemetry.store

        # Note: get_store may be called with additional kwargs like engine
        assert mock_get_store.called
        call_args = mock_get_store.call_args
        assert call_args[0][0] == "test://custom_db"
        assert telemetry._store == mock_store


class TestCleaningSessionManagement:
    """Tests for cleaning session lifecycle management."""

    def test_start_cleaning_session_enabled(self, telemetry):
        """Should start new cleaning session when telemetry enabled."""
        telemetry_id = telemetry.start_cleaning_session(
            domain="example.com",
            article_count=100,
            min_occurrences=3,
            min_boundary_score=0.3,
        )

        assert telemetry_id != ""
        assert telemetry.current_session is not None
        assert telemetry.current_session["domain"] == "example.com"
        assert telemetry.current_session["article_count"] == 100
        assert telemetry.current_session["min_occurrences"] == 3
        assert telemetry.current_session["min_boundary_score"] == 0.3
        assert telemetry.current_session["telemetry_id"] == telemetry_id
        assert isinstance(telemetry.current_session["start_time"], datetime)

        # Should reset counters
        assert telemetry.detection_counter == 0
        assert telemetry.detected_segments == []
        assert telemetry.wire_detection_events == []
        assert telemetry.locality_detection_events == []

    def test_start_cleaning_session_disabled(self, disabled_telemetry):
        """Should return empty string when telemetry disabled."""
        telemetry_id = disabled_telemetry.start_cleaning_session(
            domain="example.com", article_count=100
        )

        assert telemetry_id == ""
        assert disabled_telemetry.current_session is None

    def test_finalize_cleaning_session_enabled(self, telemetry):
        """Should finalize session and enqueue payload when enabled."""
        # Start a session first
        telemetry.start_cleaning_session(domain="example.com", article_count=100)

        # Add some test data
        telemetry.detected_segments = [{"test": "segment"}]

        # Finalize session
        telemetry.finalize_cleaning_session(
            rough_candidates_found=50,
            segments_detected=10,
            total_removable_chars=1000,
            removal_percentage=0.15,
            processing_time_ms=500.0,
        )

        # Should have updated session data
        assert telemetry.current_session is None  # Reset after finalize

        # Should have submitted to store
        telemetry._store.submit.assert_called_once()

    def test_finalize_cleaning_session_disabled(self, disabled_telemetry):
        """Should do nothing when telemetry disabled."""
        disabled_telemetry.finalize_cleaning_session(
            rough_candidates_found=50,
            segments_detected=10,
            total_removable_chars=1000,
            removal_percentage=0.15,
        )

        # Should do nothing - no assertions needed, just ensure no errors

    def test_finalize_cleaning_session_no_current_session(self, telemetry):
        """Should handle finalize when no current session exists."""
        # Don't start a session, just try to finalize
        telemetry.finalize_cleaning_session(
            rough_candidates_found=0,
            segments_detected=0,
            total_removable_chars=0,
            removal_percentage=0.0,
        )

        # Should not crash and not submit anything
        telemetry._store.submit.assert_not_called()


class TestWireDetectionLogging:
    """Tests for wire service detection logging."""

    def test_log_wire_detection_enabled(self, telemetry):
        """Should log wire detection when telemetry enabled."""
        # Start session first
        telemetry.start_cleaning_session("example.com", 100)

        telemetry.log_wire_detection(
            provider="AP",
            detection_method="regex_pattern",
            pattern_text="Associated Press",
            confidence=0.95,
            detection_stage="content_analysis",
            article_ids=["123", "456"],
            domain="custom.com",
            extra_metadata={"source": "byline"},
        )

        assert len(telemetry.wire_detection_events) == 1
        event = telemetry.wire_detection_events[0]

        assert event["provider"] == "AP"
        assert event["detection_method"] == "regex_pattern"
        assert event["pattern_text"] == "Associated Press"
        assert event["confidence"] == 0.95
        assert event["detection_stage"] == "content_analysis"
        assert event["domain"] == "custom.com"
        assert json.loads(event["article_ids_json"]) == ["123", "456"]
        assert json.loads(event["metadata_json"]) == {"source": "byline"}
        assert isinstance(event["timestamp"], datetime)

    def test_log_wire_detection_disabled(self, disabled_telemetry):
        """Should do nothing when telemetry disabled."""
        disabled_telemetry.log_wire_detection(
            provider="AP",
            detection_method="regex",
            pattern_text="test",
            confidence=0.5,
            detection_stage="test",
        )

        # Should not crash and not store anything
        assert len(disabled_telemetry.wire_detection_events) == 0

    def test_log_wire_detection_no_session(self, telemetry):
        """Should do nothing when no current session."""
        telemetry.log_wire_detection(
            provider="AP",
            detection_method="regex",
            pattern_text="test",
            confidence=0.5,
            detection_stage="test",
        )

        assert len(telemetry.wire_detection_events) == 0

    def test_log_wire_detection_defaults(self, telemetry):
        """Should handle optional parameters with defaults."""
        telemetry.start_cleaning_session("example.com", 100)

        telemetry.log_wire_detection(
            provider="Reuters",
            detection_method="keyword",
            pattern_text="Reuters",
            confidence=0.8,
            detection_stage="preprocessing",
        )

        event = telemetry.wire_detection_events[0]
        assert event["domain"] == "example.com"  # From session
        assert json.loads(event["article_ids_json"]) == []
        assert json.loads(event["metadata_json"]) == {}


class TestLocalityDetectionLogging:
    """Tests for locality detection logging."""

    def test_log_locality_detection_enabled(self, telemetry):
        """Should log locality detection when telemetry enabled."""
        telemetry.start_cleaning_session("example.com", 100)

        locality_data = {
            "is_local": True,
            "confidence": 0.85,
            "raw_score": 0.92,
            "threshold": 0.7,
            "signals": ["zip_code", "city_name"],
        }

        source_context = {"byline_location": "Columbia, MO"}

        telemetry.log_locality_detection(
            provider="AP",
            detection_method="gazetteer",
            article_id="art123",
            domain="custom.com",
            locality=locality_data,
            source_context=source_context,
        )

        assert len(telemetry.locality_detection_events) == 1
        event = telemetry.locality_detection_events[0]

        assert event["provider"] == "AP"
        assert event["detection_method"] == "gazetteer"
        assert event["article_id"] == "art123"
        assert event["domain"] == "custom.com"
        assert event["is_local"] is True
        assert event["confidence"] == 0.85
        assert event["raw_score"] == 0.92
        assert event["threshold"] == 0.7
        assert json.loads(event["signals_json"]) == ["zip_code", "city_name"]
        assert json.loads(event["locality_json"]) == locality_data
        assert json.loads(event["source_context_json"]) == source_context

    def test_log_locality_detection_empty_locality(self, telemetry):
        """Should not log when locality data is empty."""
        telemetry.start_cleaning_session("example.com", 100)

        telemetry.log_locality_detection(
            provider="AP",
            detection_method="test",
            article_id="123",
            domain="test.com",
            locality={},  # Empty locality
        )

        assert len(telemetry.locality_detection_events) == 0

    def test_log_locality_detection_disabled(self, disabled_telemetry):
        """Should do nothing when telemetry disabled."""
        locality_data = {"is_local": True, "confidence": 0.8}

        disabled_telemetry.log_locality_detection(
            provider="AP",
            detection_method="test",
            article_id="123",
            domain="test.com",
            locality=locality_data,
        )

        assert len(disabled_telemetry.locality_detection_events) == 0


class TestSegmentDetectionLogging:
    """Tests for segment detection logging."""

    def test_log_segment_detection_enabled(self, telemetry):
        """Should log segment detection when telemetry enabled."""
        telemetry.start_cleaning_session("example.com", 100)

        telemetry.log_segment_detection(
            segment_text="© 2024 Example News",
            boundary_score=0.8,
            occurrences=5,
            pattern_type="footer",
            position_consistency=0.9,
            segment_length=20,
            article_ids=["123", "456", "789"],
            was_removed=True,
            removal_reason="copyright_footer",
        )

        assert len(telemetry.detected_segments) == 1
        assert telemetry.detection_counter == 1

        segment = telemetry.detected_segments[0]
        assert segment["segment_text"] == "© 2024 Example News"
        assert segment["boundary_score"] == 0.8
        assert segment["occurrences"] == 5
        assert segment["pattern_type"] == "footer"
        assert segment["position_consistency"] == 0.9
        assert segment["segment_length"] == 20
        assert segment["affected_article_count"] == 3
        assert segment["was_removed"] is True
        assert segment["removal_reason"] == "copyright_footer"
        assert json.loads(segment["article_ids_json"]) == ["123", "456", "789"]
        assert segment["detection_number"] == 1

    def test_log_segment_detection_multiple_increments_counter(self, telemetry):
        """Should increment detection counter for multiple segments."""
        telemetry.start_cleaning_session("example.com", 100)

        # Log first segment
        telemetry.log_segment_detection(
            segment_text="First segment",
            boundary_score=0.7,
            occurrences=3,
            pattern_type="navigation",
            position_consistency=0.8,
            segment_length=10,
            article_ids=["1", "2"],
        )

        # Log second segment
        telemetry.log_segment_detection(
            segment_text="Second segment",
            boundary_score=0.6,
            occurrences=4,
            pattern_type="sidebar",
            position_consistency=0.7,
            segment_length=15,
            article_ids=["3", "4", "5"],
        )

        assert len(telemetry.detected_segments) == 2
        assert telemetry.detection_counter == 2
        assert telemetry.detected_segments[0]["detection_number"] == 1
        assert telemetry.detected_segments[1]["detection_number"] == 2

    def test_log_segment_detection_disabled(self, disabled_telemetry):
        """Should do nothing when telemetry disabled."""
        disabled_telemetry.log_segment_detection(
            segment_text="test",
            boundary_score=0.5,
            occurrences=1,
            pattern_type="test",
            position_consistency=0.5,
            segment_length=4,
            article_ids=["1"],
        )

        assert len(disabled_telemetry.detected_segments) == 0
        assert disabled_telemetry.detection_counter == 0


class TestBoundaryAssessment:
    """Tests for boundary assessment logging."""

    def test_log_boundary_assessment_enabled(self, telemetry):
        """Should store boundary assessment data."""
        telemetry.start_cleaning_session("example.com", 100)

        score_breakdown = {"capitalization": 0.3, "punctuation": 0.2, "patterns": 0.4}

        telemetry.log_boundary_assessment(
            text="This is a test boundary.",
            score=0.75,
            score_breakdown=score_breakdown,
            detected_patterns=["start_cap", "end_period"],
        )

        assessment = telemetry._last_boundary_assessment
        assert assessment is not None
        assert assessment["text"] == "This is a test boundary."
        assert assessment["final_score"] == 0.75
        assert assessment["score_breakdown"] == score_breakdown
        assert assessment["detected_patterns"] == ["start_cap", "end_period"]
        assert assessment["text_length"] == 24
        assert assessment["starts_uppercase"] is True
        assert assessment["ends_with_punctuation"] is True

    def test_log_boundary_assessment_empty_text(self, telemetry):
        """Should handle empty text gracefully."""
        telemetry.start_cleaning_session("example.com", 100)

        telemetry.log_boundary_assessment(
            text="", score=0.0, score_breakdown={}, detected_patterns=[]
        )

        assessment = telemetry._last_boundary_assessment
        assert assessment["text"] == ""
        assert assessment["text_length"] == 0
        assert assessment["starts_uppercase"] is False
        assert assessment["ends_with_punctuation"] is False

    def test_log_boundary_assessment_disabled(self, disabled_telemetry):
        """Should do nothing when telemetry disabled."""
        disabled_telemetry.log_boundary_assessment(
            text="test", score=0.5, score_breakdown={}, detected_patterns=[]
        )

        assert disabled_telemetry._last_boundary_assessment is None


class TestUtilityMethods:
    """Tests for utility methods."""

    def test_flush(self, telemetry):
        """Should call store flush when telemetry enabled."""
        telemetry.flush()
        telemetry._store.flush.assert_called_once()

    def test_flush_disabled(self, disabled_telemetry):
        """Should do nothing when telemetry disabled."""
        # Should not crash
        disabled_telemetry.flush()

    def test_shutdown_with_wait(self, telemetry):
        """Should flush when shutdown with wait=True."""
        telemetry.shutdown(wait=True)
        telemetry._store.flush.assert_called_once()

    def test_shutdown_without_wait(self, telemetry):
        """Should not flush when shutdown with wait=False."""
        telemetry.shutdown(wait=False)
        telemetry._store.flush.assert_not_called()

    def test_reset_session_state(self, telemetry):
        """Should clear all session-specific data."""
        # Set up some data
        telemetry.current_session = {"test": "data"}
        telemetry.detected_segments = [{"segment": "data"}]
        telemetry.wire_detection_events = [{"event": "data"}]
        telemetry.locality_detection_events = [{"locality": "data"}]
        telemetry.detection_counter = 5

        # Reset
        telemetry._reset_session_state()

        assert telemetry.current_session is None
        assert telemetry.detected_segments == []
        assert telemetry.wire_detection_events == []
        assert telemetry.locality_detection_events == []
        assert telemetry.detection_counter == 0


class TestPayloadBuilding:
    """Tests for payload snapshot building."""

    def test_build_payload_snapshot(self, telemetry):
        """Should create complete payload snapshot."""
        # Set up session and data
        telemetry.current_session = {"telemetry_id": "test-id", "domain": "example.com"}
        telemetry.detected_segments = [{"segment": "test"}]
        telemetry.wire_detection_events = [{"wire": "event"}]
        telemetry.locality_detection_events = [{"locality": "event"}]

        payload = telemetry._build_payload_snapshot()

        assert payload["session"] == telemetry.current_session
        assert payload["segments"] == telemetry.detected_segments
        assert payload["wire_events"] == telemetry.wire_detection_events
        assert payload["locality_events"] == (telemetry.locality_detection_events)

    def test_build_payload_snapshot_empty_session(self, telemetry):
        """Should handle empty session gracefully."""
        telemetry.current_session = None

        payload = telemetry._build_payload_snapshot()

        assert payload["session"] == {}
        assert payload["segments"] == []
        assert payload["wire_events"] == []
        assert payload["locality_events"] == []


class TestDatabaseOperations:
    """Tests for database persistence operations."""

    def test_get_persistent_patterns_success(self, telemetry, mock_store):
        """Should retrieve persistent patterns from database."""
        # Mock cursor data
        mock_conn = mock_store.connection.return_value.__enter__.return_value
        mock_cursor = mock_conn.cursor.return_value
        mock_cursor.fetchall.return_value = [
            ("footer", "© 2024 News", 0.9, 5, "copyright", 1),
            ("navigation", "Home | About", 0.8, 3, "menu", 0),
        ]

        patterns = telemetry.get_persistent_patterns("example.com")

        assert len(patterns) == 2
        assert patterns[0] == {
            "pattern_type": "footer",
            "text_content": "© 2024 News",
            "confidence_score": 0.9,
            "occurrences_total": 5,
            "removal_reason": "copyright",
            "is_ml_training_eligible": True,
        }
        assert patterns[1]["is_ml_training_eligible"] is False

    def test_get_persistent_patterns_exception(self, telemetry):
        """Should handle database exceptions gracefully."""
        with patch.object(telemetry._store, "connection") as mock_conn:
            mock_conn.side_effect = Exception("Database error")

            patterns = telemetry.get_persistent_patterns("example.com")

            assert patterns == []

    def test_ensure_persistent_patterns_table(self, telemetry, mock_store):
        """Should create table and indexes when called."""
        mock_conn = mock_store.connection.return_value.__enter__.return_value
        mock_cursor = mock_conn.cursor.return_value

        telemetry._ensure_persistent_patterns_table(mock_conn)

        # Should have called execute multiple times for table and indexes
        assert mock_cursor.execute.call_count >= 5  # 1 table + 4 indexes
        mock_cursor.close.assert_called()


class TestTelemetryPersistence:
    """Covers telemetry persistence and retrieval across the store."""

    def test_enqueue_payload_disabled_skips_writer(self, telemetry_store):
        store, _ = telemetry_store
        telemetry = ContentCleaningTelemetry(
            enable_telemetry=False,
            store=store,
        )

        telemetry._enqueue_payload({"session": {"telemetry_id": "noop"}})

        assert store.submitted == []

    def test_finalize_persists_and_updates_patterns(self, telemetry_store):
        store, conn = telemetry_store
        telemetry = ContentCleaningTelemetry(
            enable_telemetry=True,
            store=store,
        )

        telemetry.start_cleaning_session(
            domain="example.com",
            article_count=3,
            min_occurrences=2,
            min_boundary_score=0.4,
        )

        telemetry.log_segment_detection(
            segment_text="Navigation footer",
            boundary_score=0.8,
            occurrences=2,
            pattern_type="navigation",
            position_consistency=0.9,
            segment_length=180,
            article_ids=["1", "2"],
            was_removed=True,
            removal_reason="nav_footer",
        )
        telemetry.log_segment_detection(
            segment_text="Trending now",
            boundary_score=0.7,
            occurrences=1,
            pattern_type="trending",
            position_consistency=0.6,
            segment_length=120,
            article_ids=["3"],
            was_removed=True,
            removal_reason="dynamic_trending",
        )
        telemetry.log_wire_detection(
            provider="AP",
            detection_method="regex",
            pattern_text="Associated Press",
            confidence=0.9,
            detection_stage="persistent_pattern",
            article_ids=["1"],
        )
        telemetry.log_locality_detection(
            provider="AP",
            detection_method="gazetteer",
            article_id="1",
            domain="example.com",
            locality={
                "is_local": True,
                "confidence": 0.85,
                "raw_score": 0.9,
                "threshold": 0.7,
                "signals": ["county_match"],
            },
            source_context={"byline_location": "Columbia, MO"},
        )

        telemetry.finalize_cleaning_session(
            rough_candidates_found=5,
            segments_detected=2,
            total_removable_chars=300,
            removal_percentage=0.2,
            processing_time_ms=250.0,
        )

        assert len(store.submitted) == 1
        store.flush()

        cursor = conn.cursor()
        cursor.execute(
            "SELECT domain, segments_detected FROM content_cleaning_sessions"
        )
        domain, detected = cursor.fetchone()
        assert domain == "example.com"
        assert detected == 2

        cursor.execute(
            """
            SELECT pattern_type, occurrences_total, is_ml_training_eligible
            FROM persistent_boilerplate_patterns
            WHERE domain = ?
            ORDER BY pattern_type
            """,
            ("example.com",),
        )
        pattern_rows = cursor.fetchall()
        assert {row[0] for row in pattern_rows} == {
            "navigation",
            "trending",
        }
        nav_row = next(row for row in pattern_rows if row[0] == "navigation")
        assert nav_row[1] == 2
        assert nav_row[2] == 1

        telemetry.start_cleaning_session("example.com", article_count=1)
        telemetry.log_segment_detection(
            segment_text="Navigation footer",
            boundary_score=0.9,
            occurrences=1,
            pattern_type="navigation",
            position_consistency=1.0,
            segment_length=90,
            article_ids=["4"],
            was_removed=True,
            removal_reason="nav_footer",
        )
        telemetry.finalize_cleaning_session(
            rough_candidates_found=1,
            segments_detected=1,
            total_removable_chars=90,
            removal_percentage=0.1,
        )
        store.flush()

        cursor.execute(
            """
            SELECT occurrences_total
            FROM persistent_boilerplate_patterns
            WHERE domain = ? AND pattern_type = ?
            """,
            ("example.com", "navigation"),
        )
        (updated_total,) = cursor.fetchone()
        assert updated_total == 3

        patterns = telemetry.get_persistent_patterns("example.com")
        assert len(patterns) == 2

        ml_patterns = telemetry.get_ml_training_patterns("example.com")
        assert [p["pattern_type"] for p in ml_patterns] == ["navigation"]

        global_ml = telemetry.get_ml_training_patterns()
        assert any(p["domain"] == "example.com" for p in global_ml)

        telemetry_patterns = telemetry.get_telemetry_patterns(
            "example.com",
            include_dynamic=False,
        )
        assert [p["pattern_type"] for p in telemetry_patterns] == ["navigation"]

        telemetry_patterns_all = telemetry.get_telemetry_patterns(
            "example.com",
            include_dynamic=True,
        )
        assert {p["pattern_type"] for p in telemetry_patterns_all} == {
            "navigation",
            "trending",
        }

        assert telemetry.current_session is None
        assert telemetry.detected_segments == []
        assert telemetry.detection_counter == 0

        telemetry.flush()
        telemetry.shutdown(wait=True)
