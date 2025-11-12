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
from src.models import create_tables
from src.models.database import DatabaseManager, safe_execute
from tests.helpers.source_state import read_source_state


class TestPauseAfterFailures:
    """Test automatic pause after consecutive failures."""

    @pytest.fixture
    def mock_discovery(self, tmp_path):
        """Create a mock NewsDiscovery instance with SQLite for testing."""
        db_path = tmp_path / "test_pause.db"
        database_url = f"sqlite:///{db_path}"

        # Create discovery instance
        discovery = NewsDiscovery(database_url=database_url)

        # Create ORM tables (ensures typed columns exist)
        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)
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
                INSERT INTO sources (
                    id, host, host_norm, status, metadata,
                    rss_consecutive_failures, rss_transient_failures,
                    no_effective_methods_consecutive
                )
                VALUES (
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

        # Increment counter 3 times - pass source_meta for time-gating
        # For testing, we'll manually update the timestamp to bypass time gate
        source_meta = {"frequency": "daily"}
        from datetime import datetime, timedelta

        count1 = mock_discovery._increment_no_effective_methods(source_id, source_meta)
        assert count1 == 1

        # Manually update timestamp to simulate 6+ hours passing (bypass time gate)
        with db_manager.engine.begin() as conn:
            past_time = datetime.utcnow() - timedelta(hours=7)
            safe_execute(
                conn,
                """
                UPDATE sources
                SET no_effective_methods_last_seen = :past_time
                WHERE id = :id
                """,
                {"id": source_id, "past_time": past_time},
            )

        count2 = mock_discovery._increment_no_effective_methods(source_id, source_meta)
        assert count2 == 2

        # Again, manually update timestamp
        with db_manager.engine.begin() as conn:
            past_time = datetime.utcnow() - timedelta(hours=7)
            safe_execute(
                conn,
                """UPDATE sources SET no_effective_methods_last_seen = :past_time
                WHERE id = :id""",
                {"id": source_id, "past_time": past_time},
            )

        count3 = mock_discovery._increment_no_effective_methods(source_id, source_meta)
        assert count3 == 3

        # Verify typed columns were updated
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 3
        assert state.get("no_effective_methods_last_seen") is not None

        # Reset counter
        mock_discovery._reset_no_effective_methods(source_id)

        # Verify counter was reset
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 0

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
                INSERT INTO sources (
                  id, host, host_norm, status,
                  rss_consecutive_failures, rss_transient_failures,
                  no_effective_methods_consecutive
                ) VALUES (
                  :id, :host, :host_norm, :status,
                  :rss_cf, :rss_tf, :nem_cf
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 0,
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
        from datetime import datetime, timedelta

        source_id = "test-source-3"
        host = "test-site-3.com"

        # Insert a test source
        db_manager = DatabaseManager(mock_discovery.database_url)
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                    id, host, host_norm, status, metadata,
                    rss_consecutive_failures, rss_transient_failures,
                    no_effective_methods_consecutive
                )
                VALUES (
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

        # Increment to threshold - pass source_meta for time-gating
        source_meta = {"frequency": "daily"}
        count = 0
        for i in range(7):  # Daily sources need 7 failures (adaptive threshold)
            # Manually update timestamp to bypass time gate for each increment
            if i > 0:
                with db_manager.engine.begin() as conn:
                    past_time = datetime.utcnow() - timedelta(hours=7)
                    safe_execute(
                        conn,
                        """UPDATE sources
                        SET no_effective_methods_last_seen = :past_time
                        WHERE id = :id""",
                        {"id": source_id, "past_time": past_time},
                    )
            count = mock_discovery._increment_no_effective_methods(
                source_id, source_meta
            )

        # At threshold (7 for daily), pause
        if count >= 7:
            mock_discovery._pause_source(
                source_id,
                "Automatic pause after 7 consecutive failures",
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
            assert "7 consecutive failures" in row[1].lower()

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

        # Create required tables via ORM (includes typed columns)
        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)

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
                INSERT INTO sources (
                    id, host, host_norm, status, metadata,
                    rss_consecutive_failures, rss_transient_failures,
                    no_effective_methods_consecutive
                )
                VALUES (
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

        # Create source row
        source_row = pd.Series(
            {
                "id": source_id,
                "url": f"https://{host}",
                "name": host,
                "host": host,
                "metadata": json.dumps({"frequency": "daily"}),
            }
        )

        # Import for timestamp manipulation
        from datetime import datetime, timedelta

        # Mock telemetry to return no historical data and no effective methods
        with (
            patch.object(discovery, "telemetry") as mock_telemetry,
            patch.object(discovery, "_get_existing_article_count", return_value=0),
        ):
            mock_telemetry.has_historical_data.return_value = False
            mock_telemetry.get_effective_discovery_methods.return_value = []

            # Run processor 7 times (daily sources need 7 failures)
            for i in range(7):
                # Bypass time gate by updating timestamp (except first)
                if i > 0:
                    with db_manager.engine.begin() as conn:
                        past_time = datetime.utcnow() - timedelta(hours=7)
                        safe_execute(
                            conn,
                            """UPDATE sources
                            SET no_effective_methods_last_seen = :past_time
                            WHERE id = :id""",
                            {"id": source_id, "past_time": past_time},
                        )

                processor = SourceProcessor(
                    discovery=discovery,
                    source_row=source_row,
                    dataset_label=None,
                    operation_id=f"op-{i}",
                )
                # Initialize context (which sets source_meta and other attrs)
                processor._initialize_context()

                # When telemetry has no historical data, processor tries all methods
                # (gives new sources a chance before auto-pause logic kicks in)
                from src.crawler.discovery import DiscoveryMethod

                assert processor.effective_methods == [
                    DiscoveryMethod.RSS_FEED,
                    DiscoveryMethod.NEWSPAPER4K,
                ]

                # Set discovery_methods_attempted to simulate methods were tried
                processor.discovery_methods_attempted = ["rss_feed", "newspaper4k"]

                # Simulate failure by calling _record_no_articles (pass articles_new=0)
                processor._record_no_articles(articles_new=0)

        # Verify source is paused after 7th attempt (daily = 7 failures threshold)
        with db_manager.engine.connect() as conn:
            row = safe_execute(
                conn,
                "SELECT status, paused_reason FROM sources WHERE id = :id",
                {"id": source_id},
            ).fetchone()
            assert row[0] == "paused"
            assert "automatic pause" in row[1].lower()
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
