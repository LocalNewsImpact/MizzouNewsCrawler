"""
Test suite for automatic source pausing after consecutive failures.

Tests the feature that pauses sources after 3 consecutive "no effective methods"
failures when the source has never captured any articles.
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from src.crawler.discovery import NewsDiscovery
from src.crawler.source_processing import SourceProcessor
from src.models.database import DatabaseManager, safe_execute


class TestPauseAfterFailures:
    """Test automatic pause after consecutive failures."""

    @pytest.fixture
    def mock_discovery(self, tmp_path):
        """Create a mock NewsDiscovery instance with SQLite for testing."""
        db_path = tmp_path / "test_pause.db"
        database_url = f"sqlite:///{db_path}"

        # Create discovery instance
        discovery = NewsDiscovery(database_url=database_url)

        # Create sources table using DatabaseManager
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

        yield discovery

        db_manager.close()

    def test_increment_and_reset_counter(self, mock_discovery):
        """Test counter increments and resets correctly."""
        source_id = "test-source-1"
        host = "test-site.com"

        # Insert a test source
        db_manager = DatabaseManager(mock_discovery.database_url)
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

        # Increment counter 3 times
        count1 = mock_discovery._increment_no_effective_methods(source_id)
        assert count1 == 1

        count2 = mock_discovery._increment_no_effective_methods(source_id)
        assert count2 == 2

        count3 = mock_discovery._increment_no_effective_methods(source_id)
        assert count3 == 3

        # Verify metadata was updated
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 3
            assert "no_effective_methods_last_seen" in metadata

        # Reset counter
        mock_discovery._reset_no_effective_methods(source_id)

        # Verify counter was reset
        with db_manager.engine.connect() as conn:
            result = safe_execute(
                conn,
                "SELECT metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            metadata = json.loads(result[0])
            assert metadata["no_effective_methods_consecutive"] == 0

        db_manager.close()

    def test_pause_source_updates_status(self, mock_discovery):
        """Test pausing a source updates status correctly."""
        source_id = "test-source-2"
        host = "test-site-2.com"

        # Insert a test source
        db_manager = DatabaseManager(mock_discovery.database_url)
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (id, host, host_norm, status)
                VALUES (:id, :host, :host_norm, :status)
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                },
            )

        # Pause the source
        reason = "Test pause reason"
        result = mock_discovery._pause_source(source_id, reason, host=host)
        assert result is True

        # Verify source was paused
        with db_manager.engine.connect() as conn:
            row = safe_execute(
                conn,
                "SELECT status, paused_reason FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            assert row[0] == "paused"
            assert row[1] == reason

        db_manager.close()

    def test_pause_at_threshold(self, mock_discovery):
        """Test that source is paused at threshold."""
        source_id = "test-source-3"
        host = "test-site-3.com"

        # Insert a test source
        db_manager = DatabaseManager(mock_discovery.database_url)
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

        # Increment to threshold
        count = 0
        for _ in range(3):
            count = mock_discovery._increment_no_effective_methods(source_id)

        # At threshold, pause
        if count >= 3:
            mock_discovery._pause_source(
                source_id,
                "Automatic pause after 3 consecutive failures",
                host=host,
            )

        # Verify source is paused
        with db_manager.engine.connect() as conn:
            row = safe_execute(
                conn,
                "SELECT status, paused_reason FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            assert row[0] == "paused"
            assert "3 consecutive failures" in row[1].lower()

        db_manager.close()


class TestSourceProcessorPauseIntegration:
    """Integration tests for SourceProcessor pause behavior."""

    @pytest.fixture
    def mock_processor_setup(self, tmp_path):
        """Set up a mock environment for SourceProcessor testing."""
        db_path = tmp_path / "test_processor.db"
        database_url = f"sqlite:///{db_path}"

        # Create discovery instance
        discovery = NewsDiscovery(database_url=database_url)

        # Create required tables
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
                    city VARCHAR,
                    county VARCHAR,
                    owner VARCHAR,
                    type VARCHAR,
                    status VARCHAR DEFAULT 'active',
                    paused_at TIMESTAMP,
                    paused_reason TEXT,
                    metadata TEXT
                )
                """,
            )
            # Articles table (for article count check)
            safe_execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS articles (
                    id VARCHAR PRIMARY KEY,
                    candidate_link_id VARCHAR NOT NULL,
                    title TEXT,
                    content TEXT
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
                    source_id VARCHAR,
                    source_host_id VARCHAR
                )
                """,
            )

        yield discovery, database_url, db_manager

        db_manager.close()

    def test_processor_pauses_after_three_failures(self, mock_processor_setup):
        """Test that SourceProcessor pauses source after 3 consecutive failures."""
        discovery, database_url, db_manager = mock_processor_setup
        source_id = "test-source-4"
        host = "test-site-4.com"

        # Insert test source
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

        # Create source row
        source_row = pd.Series(
            {
                "id": source_id,
                "url": f"https://{host}",
                "name": host,
                "host": host,
            }
        )

        # Mock telemetry to return no historical data and no effective methods
        with patch.object(
            discovery, "telemetry"
        ) as mock_telemetry, patch.object(
            discovery, "_get_existing_article_count", return_value=0
        ):
            mock_telemetry.has_historical_data.return_value = False
            mock_telemetry.get_effective_discovery_methods.return_value = []

            # Run processor 3 times
            for i in range(3):
                processor = SourceProcessor(
                    discovery=discovery,
                    source_row=source_row,
                    dataset_label=None,
                    operation_id=f"op-{i}",
                )
                # Initialize context (which sets source_meta and other attrs)
                processor._initialize_context()

                # Check methods after initialization - should be empty
                # (triggers pause logic on 3rd iteration)
                assert processor.effective_methods == []

        # Verify source is paused after 3rd attempt
        with db_manager.engine.connect() as conn:
            row = safe_execute(
                conn,
                "SELECT status, paused_reason, metadata FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()

            assert row[0] == "paused"
            assert "automatic pause" in row[1].lower()

            metadata = json.loads(row[2])
            assert metadata["no_effective_methods_consecutive"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
