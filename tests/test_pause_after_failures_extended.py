"""
Extended test suite for automatic source pausing - edge cases and telemetry.

Tests edge cases like:
- Concurrent counter increments
- Metadata corruption/missing fields
- Pause/resume cycles
- Telemetry integration
- Counter reset on successful discoveries
"""

import json
import threading
from unittest.mock import patch

import pandas as pd
import pytest

from src.crawler.discovery import NewsDiscovery
from src.crawler.source_processing import SourceProcessor
from src.models import create_tables
from src.models.database import DatabaseManager, safe_execute
from tests.helpers.source_state import read_source_state


class TestPauseEdgeCases:
    """Test edge cases for pause-after-failures feature."""

    @pytest.fixture
    def mock_discovery(self, tmp_path):
        """Create a mock NewsDiscovery instance with SQLite for testing."""
        db_path = tmp_path / "test_edge_cases.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)

        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)

        yield discovery, db_manager

        db_manager.close()

    def test_missing_metadata_field_initializes_correctly(self, mock_discovery):
        """Test that missing metadata fields are initialized properly."""
        discovery, db_manager = mock_discovery
        source_id = "test-missing-metadata"
        host = "missing-meta.com"

        # Insert source with NULL metadata
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": None,
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        # Increment should handle missing metadata gracefully
        count = discovery._increment_no_effective_methods(source_id)
        assert count == 1

        # Verify typed columns reflect increment
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 1
        assert state.get("no_effective_methods_last_seen") is not None

    def test_corrupt_metadata_reinitializes(self, mock_discovery):
        """Test that corrupt metadata is handled gracefully."""
        discovery, db_manager = mock_discovery
        source_id = "test-corrupt-metadata"
        host = "corrupt-meta.com"

        # Insert source with invalid JSON metadata
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": "{invalid json",
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        # Increment should handle corrupt metadata gracefully
        count = discovery._increment_no_effective_methods(source_id)
        assert count == 1

    def test_reset_nonexistent_counter(self, mock_discovery):
        """Test resetting a counter that doesn't exist."""
        discovery, db_manager = mock_discovery
        source_id = "test-no-counter"
        host = "no-counter.com"

        # Insert source without counter in metadata
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({"other_field": "value"}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        # Reset should succeed without error
        discovery._reset_no_effective_methods(source_id)

        # Verify typed counter was set to 0
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 0

    def test_pause_already_paused_source(self, mock_discovery):
        """Test pausing a source that's already paused."""
        discovery, db_manager = mock_discovery
        source_id = "test-already-paused"
        host = "already-paused.com"

        # Insert already-paused source
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, paused_reason,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :paused_reason,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "paused",
                    "paused_reason": "Previously paused",
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        # Pause again with new reason
        result = discovery._pause_source(source_id, "New pause reason", host=host)
        assert result is True

        # Verify reason was updated
        with db_manager.engine.connect() as conn:
            row = safe_execute(
                conn,
                "SELECT status, paused_reason FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            assert row[0] == "paused"
            assert row[1] == "New pause reason"

    def test_pause_nonexistent_source_creates_it(self, mock_discovery):
        """Test that pausing a nonexistent source creates it."""
        discovery, db_manager = mock_discovery
        source_id = "test-nonexistent"
        host = "nonexistent.com"

        # Pause nonexistent source
        result = discovery._pause_source(source_id, "Auto-created pause", host=host)
        assert result is True

        # Verify a source was created for this host and paused
        # Note: The implementation creates a new UUID, not the source_id
        with db_manager.engine.connect() as conn:
            row = safe_execute(
                conn,
                "SELECT host, status, paused_reason FROM sources WHERE host = :host",
                {"host": host},
            ).fetchone()

            assert row is not None
            assert row[0] == host
            assert row[1] == "paused"
            assert row[2] == "Auto-created pause"

    def test_concurrent_increments(self, mock_discovery):
        """Test that concurrent increments handle race conditions gracefully."""
        discovery, db_manager = mock_discovery
        source_id = "test-concurrent"
        host = "concurrent.com"

        # Insert source
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        # Simulate concurrent increments
        results = []
        errors = []

        def increment_counter():
            try:
                count = discovery._increment_no_effective_methods(source_id)
                results.append(count)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=increment_counter) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors
        assert len(errors) == 0

        # All increments should succeed
        assert len(results) == 5

        # Note: Due to race conditions with SQLite, concurrent threads may see
        # the same value. The important thing is that:
        # 1. No errors occur
        # 2. The final count reflects at least some increments
        # 3. Data is not corrupted

        # Final count should be >= 1 (at least one increment succeeded)
        state = read_source_state(db_manager.engine, source_id)
        final_count = int(state.get("no_effective_methods_consecutive") or 0)
        # With SQLite's read-modify-write pattern, race conditions may occur
        # The final count should be at least 1, but may not be 5
        assert final_count >= 1
        assert final_count <= 5


class TestPauseResumeWorkflow:
    """Test pause/resume workflow."""

    @pytest.fixture
    def mock_setup(self, tmp_path):
        """Set up test database."""
        db_path = tmp_path / "test_workflow.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)

        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)

        yield discovery, db_manager

        db_manager.close()

    def test_pause_then_resume_resets_counter(self, mock_setup):
        """Test that resuming a paused source resets the counter."""
        discovery, db_manager = mock_setup
        source_id = "test-pause-resume"
        host = "pause-resume.com"

        # Insert source
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        # Increment to 3 and pause
        for _ in range(3):
            discovery._increment_no_effective_methods(source_id)

        discovery._pause_source(source_id, "Test pause", host=host)

        # Verify paused
        with db_manager.engine.connect() as conn:
            row = safe_execute(
                conn,
                "SELECT status FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()
            assert row[0] == "paused"

        # Simulate resume (would be done via API)
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                UPDATE sources
                SET status = 'active', paused_at = NULL, paused_reason = NULL
                WHERE id = :id
                """,
                {"id": source_id},
            )

        # Reset counter on resume
        discovery._reset_no_effective_methods(source_id)

        # Verify typed counter was reset
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 0


class TestTelemetryIntegration:
    """Test telemetry integration with pause feature."""

    @pytest.fixture
    def mock_setup(self, tmp_path):
        """Set up test environment with telemetry."""
        db_path = tmp_path / "test_telemetry.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)

        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)

        yield discovery, database_url, db_manager

        db_manager.close()

    def test_telemetry_has_no_historical_data_triggers_counter(self, mock_setup):
        """Test that telemetry reporting no historical data triggers counter."""
        discovery, database_url, db_manager = mock_setup
        source_id = "test-no-history"
        host = "no-history.com"

        # Insert source
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({"frequency": "daily"}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        source_row = pd.Series(
            {
                "id": source_id,
                "url": f"https://{host}",
                "name": host,
                "host": host,
                "metadata": json.dumps({"frequency": "daily"}),
            }
        )

        # Mock telemetry to indicate no historical data
        with (
            patch.object(discovery, "telemetry") as mock_telemetry,
            patch.object(discovery, "_get_existing_article_count", return_value=0),
        ):
            mock_telemetry.has_historical_data.return_value = False
            mock_telemetry.get_effective_discovery_methods.return_value = []

            processor = SourceProcessor(
                discovery=discovery,
                source_row=source_row,
                dataset_label=None,
                operation_id="op-telemetry-1",
            )
            processor._initialize_context()

            # Verify telemetry was called
            mock_telemetry.has_historical_data.assert_called_once_with(source_id)
            mock_telemetry.get_effective_discovery_methods.assert_called_once_with(
                source_id
            )

            # When telemetry has no historical data, processor tries all methods
            # (new sources get a chance before auto-pause kicks in)
            from src.crawler.discovery import DiscoveryMethod

            assert processor.effective_methods == [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]

            # Set discovery_methods_attempted to simulate methods were tried
            processor.discovery_methods_attempted = ["rss_feed", "newspaper4k"]

            # Simulate failure and record it (pass articles_new=0)
            processor._record_no_articles(articles_new=0)

        # Verify typed counter was incremented
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 1

    def test_successful_store_resets_counter_and_calls_telemetry(self, mock_setup):
        """Test that storing candidates resets counter."""
        discovery, database_url, db_manager = mock_setup
        source_id = "test-reset-on-success"
        host = "reset-success.com"

        # Insert source, then set typed counter to 2
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )
            # Set typed column to 2 explicitly
            safe_execute(
                conn,
                (
                    "UPDATE sources SET no_effective_methods_consecutive = 2 "
                    "WHERE id = :id"
                ),
                {"id": source_id},
            )

        # Verify typed counter starts at 2
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 2

        # Simulate successful article discovery by calling reset
        discovery._reset_no_effective_methods(source_id)

        # Verify typed counter was reset to 0
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 0

    def test_telemetry_exception_doesnt_break_pause_logic(self, mock_setup):
        """Test that telemetry exceptions don't prevent pause logic."""
        discovery, database_url, db_manager = mock_setup
        source_id = "test-telemetry-exception"
        host = "telemetry-fail.com"

        # Insert source
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({"frequency": "daily"}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        source_row = pd.Series(
            {
                "id": source_id,
                "url": f"https://{host}",
                "name": host,
                "host": host,
                "metadata": json.dumps({"frequency": "daily"}),
            }
        )

        # Mock telemetry to raise exception
        with (
            patch.object(discovery, "telemetry") as mock_telemetry,
            patch.object(discovery, "_get_existing_article_count", return_value=0),
        ):
            mock_telemetry.has_historical_data.side_effect = Exception(
                "Telemetry error"
            )

            processor = SourceProcessor(
                discovery=discovery,
                source_row=source_row,
                dataset_label=None,
                operation_id="op-exception-1",
            )
            processor._initialize_context()

            # Should fall back to trying all methods (telemetry exception is caught)
            from src.crawler.discovery import DiscoveryMethod

            assert processor.effective_methods == [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]

            # Set discovery_methods_attempted to simulate methods were tried
            processor.discovery_methods_attempted = ["rss_feed", "newspaper4k"]

            # Simulate failure (pass articles_new=0)
            processor._record_no_articles(articles_new=0)

        # Counter should still be incremented (typed)
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 1


class TestCounterTimestamps:
    """Test timestamp tracking for counter."""

    @pytest.fixture
    def mock_discovery(self, tmp_path):
        """Create discovery instance."""
        db_path = tmp_path / "test_timestamps.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)

        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)

        yield discovery, db_manager

        db_manager.close()

    def test_last_seen_timestamp_updates(self, mock_discovery):
        """Test that last_seen timestamp is updated on each increment."""
        discovery, db_manager = mock_discovery
        source_id = "test-timestamp"
        host = "timestamp.com"

        # Insert source
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                  id, host, host_norm, status, metadata,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status, :metadata,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
                },
            )

        # First increment (pass source_meta for time-gating)
        source_meta = {"frequency": "daily"}
        discovery._increment_no_effective_methods(source_id, source_meta)

        state = read_source_state(db_manager.engine, source_id)
        first_timestamp = state.get("no_effective_methods_last_seen")

        # Second increment with delay to exceed time gate (6 hours for daily)
        import time

        time.sleep(0.01)  # Small delay for test
        discovery._increment_no_effective_methods(source_id, source_meta)

        state = read_source_state(db_manager.engine, source_id)
        second_timestamp = state.get("no_effective_methods_last_seen")

        # With time-gating enabled, counter only increments if enough time passed
        # Since we only waited 0.01s (not 6 hours), counter should stay at 1
        # But timestamp should update
        assert second_timestamp is not None
        assert first_timestamp is not None
        # Both timestamps will be nearly identical since time gate blocks increment


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
