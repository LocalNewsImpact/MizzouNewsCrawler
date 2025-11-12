"""
Test suite for time-gated failure counting.

Tests the feature that prevents over-counting failures when sources
are checked more frequently than their publication frequency.

These are SQLite-based unit tests (using `tmp_path` for a temporary
SQLite database). They are intended to run in the default CI integration
job (no pytest marker needed).

This differentiates them from the PostgreSQL integration tests in
`tests/integration/test_time_gated_failure_persistence.py`, which require
@pytest.mark.integration and run in the postgres-integration CI job.
"""

import json
from datetime import datetime, timedelta

import pytest

from src.crawler.discovery import NewsDiscovery
from src.models import create_tables
from src.models.database import DatabaseManager, safe_execute
from tests.helpers.source_state import read_source_state


class TestTimeGatedFailureCounting:
    """Test time-gated failure counting prevents over-counting."""

    @pytest.fixture
    def mock_discovery(self, tmp_path):
        """Create a mock NewsDiscovery instance with SQLite for testing."""
        db_path = tmp_path / "test_time_gating.db"
        database_url = f"sqlite:///{db_path}"

        discovery = NewsDiscovery(database_url=database_url)
        db_manager = DatabaseManager(database_url)
        create_tables(db_manager.engine)
        yield discovery
        db_manager.close()

    def _insert_test_source(
        self,
        db_manager,
        source_id: str,
        host: str,
        frequency: str = "weekly",
        last_seen: datetime | None = None,
        current_count: int = 0,
    ):
        """Helper to insert a test source with specific state."""
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                    id, host, host_norm, status, metadata,
                    rss_consecutive_failures, rss_transient_failures,
                    no_effective_methods_consecutive,
                    no_effective_methods_last_seen
                )
                VALUES (
                    :id, :host, :host_norm, :status, :metadata,
                    :rss_cf, :rss_tf, :nem_cf, :nem_last_seen
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({"frequency": frequency}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": current_count,
                    "nem_last_seen": last_seen,
                },
            )

    def test_first_failure_always_counts(self, mock_discovery):
        """First failure should always increment counter (no last_seen)."""
        source_id = "test-first-failure"
        host = "first.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with no previous failures
        self._insert_test_source(db_manager, source_id, host, frequency="weekly")

        # Increment should always work for first failure
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        assert count == 1

        # Verify timestamp was set
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 1
        assert state.get("no_effective_methods_last_seen") is not None

        db_manager.close()

    def test_daily_source_blocks_rapid_checks(self, mock_discovery):
        """
        Daily source should block checks within 6 hours (0.25 days).

        According to parse_frequency_to_days(), a "daily" frequency is
        interpreted as 0.25 days, so the time gate is 0.25 * 24 = 6 hours.
        This test ensures that a source with "daily" frequency does not
        increment its failure count if checked again within this 6-hour
        window.
        """
        source_id = "test-daily-rapid"
        host = "daily.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 3 hours ago
        last_seen = datetime.utcnow() - timedelta(hours=3)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="daily",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment again (should be blocked)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "daily"},
        )

        # Count should remain 1 (not incremented)
        assert count == 1

        # Verify database wasn't updated
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 1

        db_manager.close()

    def test_daily_source_allows_after_6_hours(self, mock_discovery):
        """Daily source should allow increment after 6+ hours."""
        source_id = "test-daily-allowed"
        host = "daily-allowed.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 7 hours ago
        last_seen = datetime.utcnow() - timedelta(hours=7)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="daily",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should succeed)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "daily"},
        )

        # Count should be incremented to 2
        assert count == 2

        # Verify database was updated
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 2

        db_manager.close()

    def test_weekly_source_blocks_daily_checks(self, mock_discovery):
        """Weekly source should block checks within 7 days."""
        source_id = "test-weekly-rapid"
        host = "weekly.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 2 days ago
        last_seen = datetime.utcnow() - timedelta(days=2)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="weekly",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should be blocked)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        assert count == 1  # Should remain 1

        db_manager.close()

    def test_weekly_source_allows_after_7_days(self, mock_discovery):
        """Weekly source should allow increment after 7+ days."""
        source_id = "test-weekly-allowed"
        host = "weekly-allowed.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 8 days ago
        last_seen = datetime.utcnow() - timedelta(days=8)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="weekly",
            last_seen=last_seen,
            current_count=2,
        )

        # Try to increment (should succeed)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        assert count == 3  # Should increment to 3

        db_manager.close()

    def test_monthly_source_requires_30_days(self, mock_discovery):
        """Monthly source should require 30 days between increments."""
        source_id = "test-monthly"
        host = "monthly.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 14 days ago
        last_seen = datetime.utcnow() - timedelta(days=14)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="monthly",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should be blocked - only 14 days)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "monthly"},
        )

        assert count == 1  # Should remain 1

        db_manager.close()

    def test_monthly_source_allows_after_30_days(self, mock_discovery):
        """Monthly source should allow increment after 30+ days."""
        source_id = "test-monthly-allowed"
        host = "monthly-allowed.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 31 days ago
        last_seen = datetime.utcnow() - timedelta(days=31)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="monthly",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should succeed)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "monthly"},
        )

        assert count == 2  # Should increment to 2

        db_manager.close()

    def test_unknown_frequency_defaults_to_7_days(self, mock_discovery):
        """Unknown frequency should default to 7 days (weekly)."""
        source_id = "test-unknown-freq"
        host = "unknown.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 3 days ago
        last_seen = datetime.utcnow() - timedelta(days=3)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="unknown",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should be blocked - only 3 days)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "unknown"},
        )

        assert count == 1  # Should remain 1

        db_manager.close()

    def test_no_metadata_defaults_to_7_days(self, mock_discovery):
        """No metadata should default to 7 days between increments."""
        source_id = "test-no-meta"
        host = "nometa.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 3 days ago
        last_seen = datetime.utcnow() - timedelta(days=3)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="daily",  # Will be ignored since we pass None
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment without source_meta
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta=None,  # No metadata
        )

        assert count == 1  # Should remain 1 (blocked by default 7 days)

        db_manager.close()

    def test_multiple_rapid_checks_same_result(self, mock_discovery):
        """Multiple rapid checks should all return same count."""
        source_id = "test-multiple-rapid"
        host = "rapid.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 1 hour ago
        last_seen = datetime.utcnow() - timedelta(hours=1)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="daily",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment multiple times rapidly
        for _ in range(5):
            count = mock_discovery._increment_no_effective_methods(
                source_id,
                source_meta={"frequency": "daily"},
            )
            assert count == 1  # Should always be 1

        # Verify database still shows 1
        state = read_source_state(db_manager.engine, source_id)
        assert state.get("no_effective_methods_consecutive") == 1

        db_manager.close()

    def test_exact_boundary_allows_increment(self, mock_discovery):
        """Exactly at time boundary should allow increment."""
        source_id = "test-exact-boundary"
        host = "boundary.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure exactly 7 days ago
        last_seen = datetime.utcnow() - timedelta(days=7, seconds=1)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="weekly",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should succeed)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        assert count == 2  # Should increment

        db_manager.close()

    def test_biweekly_requires_14_days(self, mock_discovery):
        """Bi-weekly source should require 14 days between increments."""
        source_id = "test-biweekly"
        host = "biweekly.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 7 days ago
        last_seen = datetime.utcnow() - timedelta(days=7)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="bi-weekly",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should be blocked - only 7 days)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "bi-weekly"},
        )

        assert count == 1  # Should remain 1

        db_manager.close()

    def test_biweekly_allows_after_14_days(self, mock_discovery):
        """Bi-weekly source should allow increment after 14+ days."""
        source_id = "test-biweekly-allowed"
        host = "biweekly-allowed.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 15 days ago
        last_seen = datetime.utcnow() - timedelta(days=15)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="bi-weekly",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should succeed)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "bi-weekly"},
        )

        assert count == 2  # Should increment to 2

        db_manager.close()

    def test_iso_format_timestamp_parsing(self, mock_discovery):
        """Test that ISO format timestamps (string) are parsed correctly."""
        source_id = "test-iso-timestamp"
        host = "iso.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with ISO format timestamp string
        last_seen_iso = (datetime.utcnow() - timedelta(days=2)).isoformat()
        with db_manager.engine.begin() as conn:
            safe_execute(
                conn,
                """
                INSERT INTO sources (
                    id, host, host_norm, status, metadata,
                    rss_consecutive_failures, rss_transient_failures,
                    no_effective_methods_consecutive,
                    no_effective_methods_last_seen
                )
                VALUES (
                    :id, :host, :host_norm, :status, :metadata,
                    :rss_cf, :rss_tf, :nem_cf, :nem_last_seen
                )
                """,
                {
                    "id": source_id,
                    "host": host,
                    "host_norm": host.lower(),
                    "status": "active",
                    "metadata": json.dumps({"frequency": "weekly"}),
                    "rss_cf": 0,
                    "rss_tf": json.dumps([]),
                    "nem_cf": 1,
                    "nem_last_seen": last_seen_iso,  # String format
                },
            )

        # Try to increment (should be blocked - only 2 days)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        assert count == 1  # Should remain 1

        db_manager.close()

    def test_counter_progresses_correctly_over_time(self, mock_discovery):
        """Test that counter progresses correctly when checked weekly."""
        source_id = "test-progression"
        host = "progression.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Start with no previous failures
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="weekly",
            last_seen=None,
            current_count=0,
        )

        # First failure (week 1)
        count1 = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )
        assert count1 == 1

        # Simulate waiting 8 days, then checking again
        with db_manager.engine.begin() as conn:
            past_date = datetime.utcnow() - timedelta(days=8)
            safe_execute(
                conn,
                """
                UPDATE sources
                SET no_effective_methods_last_seen = :ts
                WHERE id = :id
                """,
                {"ts": past_date, "id": source_id},
            )

        # Second failure (week 2)
        count2 = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )
        assert count2 == 2

        # Simulate waiting another 8 days
        with db_manager.engine.begin() as conn:
            past_date = datetime.utcnow() - timedelta(days=8)
            safe_execute(
                conn,
                """
                UPDATE sources
                SET no_effective_methods_last_seen = :ts
                WHERE id = :id
                """,
                {"ts": past_date, "id": source_id},
            )

        # Third failure (week 3)
        count3 = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )
        assert count3 == 3

        db_manager.close()

    def test_broadcast_frequency_treated_as_daily(self, mock_discovery):
        """Broadcast frequency should be treated as daily (6 hours)."""
        source_id = "test-broadcast"
        host = "broadcast.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 3 hours ago
        last_seen = datetime.utcnow() - timedelta(hours=3)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="broadcast",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should be blocked - only 3 hours)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "broadcast"},
        )

        assert count == 1  # Should remain 1

        db_manager.close()

    def test_hourly_frequency_requires_1_day(self, mock_discovery):
        """Hourly frequency should require 1 day between increments."""
        source_id = "test-hourly"
        host = "hourly.com"
        db_manager = DatabaseManager(mock_discovery.database_url)

        # Insert source with failure 12 hours ago
        last_seen = datetime.utcnow() - timedelta(hours=12)
        self._insert_test_source(
            db_manager,
            source_id,
            host,
            frequency="hourly",
            last_seen=last_seen,
            current_count=1,
        )

        # Try to increment (should be blocked - only 12 hours)
        count = mock_discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "hourly"},
        )

        assert count == 1  # Should remain 1

        db_manager.close()
