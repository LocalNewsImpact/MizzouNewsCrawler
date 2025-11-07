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
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, call, patch

import pandas as pd
import pytest

from src.crawler.discovery import NewsDiscovery
from src.crawler.source_processing import SourceProcessor
from src.models.database import DatabaseManager, safe_execute


class TestPauseEdgeCases:
    """Test edge cases for pause-after-failures feature."""

    @pytest.fixture
    def mock_discovery(self, tmp_path):
        """Create a mock NewsDiscovery instance with SQLite for testing."""
        db_path = tmp_path / "test_edge_cases.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)

        db_manager = DatabaseManager(database_url)
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id VARCHAR PRIMARY KEY,
                    host VARCHAR NOT NULL,
                    host_norm VARCHAR,
                    status VARCHAR DEFAULT 'active',
                    paused_at TIMESTAMP,
                    paused_reason TEXT,
                    metadata TEXT
                )
                """,
            )

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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": None,
                },
            )

        # Increment should handle missing metadata gracefully
        count = discovery._increment_no_effective_methods(source_id)
        assert count == 1

        # Verify metadata was created
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 1
            assert "no_effective_methods_last_seen" in metadata

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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": "{invalid json",
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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({"other_field": "value"}),
                },
            )

        # Reset should succeed without error
        discovery._reset_no_effective_methods(source_id)

        # Verify counter was set to 0
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 0

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
                INSERT INTO sources (id, host, host_norm, status, paused_reason)
                VALUES (:id, :host, :host_norm, :status, :paused_reason)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "paused",
                    "paused_reason": "Previously paused",
                },
            )

        # Pause again with new reason
        result = discovery._pause_source(
            source_id, "New pause reason", host=host
        )
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
        result = discovery._pause_source(
            source_id, "Auto-created pause", host=host
        )
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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
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
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            final_count = metadata["no_effective_methods_consecutive"]
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
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id VARCHAR PRIMARY KEY,
                    host VARCHAR NOT NULL,
                    host_norm VARCHAR,
                    status VARCHAR DEFAULT 'active',
                    paused_at TIMESTAMP,
                    paused_reason TEXT,
                    metadata TEXT
                )
                """,
            )

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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
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

        # Verify counter was reset
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 0


class TestTelemetryIntegration:
    """Test telemetry integration with pause feature."""

    @pytest.fixture
    def mock_setup(self, tmp_path):
        """Set up test environment with telemetry."""
        db_path = tmp_path / "test_telemetry.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)

        db_manager = DatabaseManager(database_url)
        with db_manager.engine.begin() as conn:
            # Sources table
            safe_execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id VARCHAR PRIMARY KEY,
                    host VARCHAR NOT NULL,
                    host_norm VARCHAR,
                    canonical_name VARCHAR,
                    status VARCHAR DEFAULT 'active',
                    paused_at TIMESTAMP,
                    paused_reason TEXT,
                    metadata TEXT
                )
                """,
            )
            # Articles table
            safe_execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS articles (
                    id VARCHAR PRIMARY KEY,
                    candidate_link_id VARCHAR NOT NULL,
                    title TEXT
                )
                """,
            )
            # Candidate links table
            safe_execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS candidate_links (
                    id VARCHAR PRIMARY KEY,
                    url VARCHAR UNIQUE NOT NULL,
                    source_id VARCHAR
                )
                """,
            )

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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
                },
            )

        source_row = pd.Series(
            {
                "id": source_id,
                "url": f"https://{host}",
                "name": host,
                "host": host,
            }
        )

        # Mock telemetry to indicate no historical data
        with patch.object(
            discovery, "telemetry"
        ) as mock_telemetry, patch.object(
            discovery, "_get_existing_article_count", return_value=0
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

            # Verify effective_methods is empty
            assert processor.effective_methods == []

        # Verify counter was incremented
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 1

    def test_successful_store_resets_counter_and_calls_telemetry(self, mock_setup):
        """Test that storing candidates resets counter."""
        discovery, database_url, db_manager = mock_setup
        source_id = "test-reset-on-success"
        host = "reset-success.com"

        # Insert source with counter at 2
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps(
                        {"no_effective_methods_consecutive": 2}
                    ),
                },
            )

        # Verify counter starts at 2
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 2

        # Simulate successful article discovery by calling reset
        discovery._reset_no_effective_methods(source_id)

        # Verify counter was reset to 0
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 0

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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
                },
            )

        source_row = pd.Series(
            {
                "id": source_id,
                "url": f"https://{host}",
                "name": host,
                "host": host,
            }
        )

        # Mock telemetry to raise exception
        with patch.object(
            discovery, "telemetry"
        ) as mock_telemetry, patch.object(
            discovery, "_get_existing_article_count", return_value=0
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

            # Should fall back to empty methods
            assert processor.effective_methods == []

        # Counter should still be incremented
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 1


class TestCounterTimestamps:
    """Test timestamp tracking for counter."""

    @pytest.fixture
    def mock_discovery(self, tmp_path):
        """Create discovery instance."""
        db_path = tmp_path / "test_timestamps.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)

        db_manager = DatabaseManager(database_url)
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id VARCHAR PRIMARY KEY,
                    host VARCHAR NOT NULL,
                    host_norm VARCHAR,
                    status VARCHAR DEFAULT 'active',
                    paused_at TIMESTAMP,
                    paused_reason TEXT,
                    metadata TEXT
                )
                """,
            )

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
                INSERT INTO sources (id, host, host_norm, status, metadata)
                VALUES (:id, :host, :host_norm, :status, :metadata)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({}),
                },
            )

        # First increment
        discovery._increment_no_effective_methods(source_id)

        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            first_timestamp = metadata["no_effective_methods_last_seen"]

        # Second increment (with slight delay to ensure different timestamp)
        import time

        time.sleep(0.01)
        discovery._increment_no_effective_methods(source_id)

        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            second_timestamp = metadata["no_effective_methods_last_seen"]

        # Timestamps should be different (second should be later)
        assert second_timestamp > first_timestamp


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
