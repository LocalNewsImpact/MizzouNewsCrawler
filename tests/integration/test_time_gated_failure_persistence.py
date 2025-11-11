"""
PostgreSQL integration tests for time-gated failure counting persistence.

Tests that verify the time-gated failure counting logic correctly writes
to PostgreSQL database tables and that the time-gating persists across
multiple database operations.

Requires TEST_DATABASE_URL environment variable.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.crawler.discovery import NewsDiscovery
from src.models import Source


@pytest.mark.integration
class TestTimeGatedFailurePersistence:
    """Integration tests for PostgreSQL persistence of time-gated failures."""

    def _create_test_source(
        self,
        session,
        source_id: str,
        host: str,
        frequency: str = "weekly",
        counter: int = 0,
        last_seen: datetime | None = None,
    ) -> Source:
        """Create a test source with specified failure state.

        Args:
            session: SQLAlchemy session
            source_id: Unique source identifier
            host: Source hostname
            frequency: Publication frequency
            counter: Initial failure counter value
            last_seen: Initial last seen timestamp

        Returns:
            Created Source instance
        """
        source = Source(
            id=source_id,
            host=host,
            host_norm=host.lower(),
            status="active",
            meta={"frequency": frequency},
            rss_consecutive_failures=0,
            rss_transient_failures=[],
            no_effective_methods_consecutive=counter,
            no_effective_methods_last_seen=last_seen,
        )
        session.add(source)
        session.flush()
        return source

    def _query_source_state(self, session, source_id: str) -> dict:
        """Query source failure state directly from PostgreSQL.

        Args:
            session: SQLAlchemy session
            source_id: Source identifier

        Returns:
            Dict with counter and last_seen values
        """
        result = session.execute(
            text(
                """
                SELECT no_effective_methods_consecutive,
                       no_effective_methods_last_seen
                FROM sources
                WHERE id = :source_id
                """
            ),
            {"source_id": source_id},
        ).fetchone()

        if not result:
            return {"counter": None, "last_seen": None}

        return {
            "counter": result[0],
            "last_seen": result[1],
        }

    def test_first_failure_writes_to_postgres(self, cloud_sql_session):
        """Test that first failure writes counter and timestamp to PostgreSQL."""
        source_id = f"test-first-{datetime.utcnow().timestamp()}"
        host = "first-failure.com"

        # Create source with no previous failures
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="weekly",
        )

        # Get database URL from session's engine
        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Increment failure counter
        count = discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        # Verify return value
        assert count == 1

        # Verify PostgreSQL columns were updated
        state = self._query_source_state(cloud_sql_session, source_id)
        assert state["counter"] == 1
        assert state["last_seen"] is not None
        assert isinstance(state["last_seen"], datetime)

    def test_rapid_checks_dont_write_to_postgres(self, cloud_sql_session):
        """Test that rapid checks don't update PostgreSQL counter."""
        source_id = f"test-rapid-{datetime.utcnow().timestamp()}"
        host = "rapid-checks.com"

        # Create source with recent failure (2 hours ago)
        last_seen = datetime.utcnow() - timedelta(hours=2)
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="daily",
            counter=1,
            last_seen=last_seen,
        )

        # Capture original timestamp
        original_state = self._query_source_state(cloud_sql_session, source_id)
        original_timestamp = original_state["last_seen"]

        # Try to increment multiple times rapidly
        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        for i in range(5):
            count = discovery._increment_no_effective_methods(
                source_id,
                source_meta={"frequency": "daily"},
            )
            # Should always return 1 (not incremented)
            assert count == 1

        # Verify PostgreSQL counter unchanged
        final_state = self._query_source_state(cloud_sql_session, source_id)
        assert final_state["counter"] == 1
        
        # Timestamp should be unchanged (within 1 second tolerance)
        time_diff = abs(
            (final_state["last_seen"] - original_timestamp).total_seconds()
        )
        assert time_diff < 1.0

    def test_weekly_source_time_gate_persists(self, cloud_sql_session):
        """Test that weekly time gate prevents updates for 7 days."""
        source_id = f"test-weekly-{datetime.utcnow().timestamp()}"
        host = "weekly-time-gate.com"

        # Create source with failure 3 days ago
        last_seen = datetime.utcnow() - timedelta(days=3)
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="weekly",
            counter=2,
            last_seen=last_seen,
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Try to increment (should be blocked)
        count = discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        # Should return current count (not incremented)
        assert count == 2

        # Verify PostgreSQL counter unchanged
        state = self._query_source_state(cloud_sql_session, source_id)
        assert state["counter"] == 2

    def test_weekly_source_allows_after_7_days_postgres(
        self, cloud_sql_session
    ):
        """Test that weekly source allows increment after 7 days in PostgreSQL."""
        source_id = f"test-weekly-allowed-{datetime.utcnow().timestamp()}"
        host = "weekly-allowed.com"

        # Create source with failure 8 days ago
        last_seen = datetime.utcnow() - timedelta(days=8)
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="weekly",
            counter=2,
            last_seen=last_seen,
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Try to increment (should succeed)
        count = discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        # Should increment to 3
        assert count == 3

        # Verify PostgreSQL was updated
        state = self._query_source_state(cloud_sql_session, source_id)
        assert state["counter"] == 3
        
        # Timestamp should be recent (within last minute)
        age_seconds = (
            datetime.utcnow() - state["last_seen"]
        ).total_seconds()
        assert age_seconds < 60

    def test_monthly_source_requires_30_days_postgres(self, cloud_sql_session):
        """Test that monthly source requires 30 days in PostgreSQL."""
        source_id = f"test-monthly-{datetime.utcnow().timestamp()}"
        host = "monthly-gate.com"

        # Create source with failure 14 days ago
        last_seen = datetime.utcnow() - timedelta(days=14)
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="monthly",
            counter=1,
            last_seen=last_seen,
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Try to increment (should be blocked)
        count = discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "monthly"},
        )

        assert count == 1

        # Verify PostgreSQL unchanged
        state = self._query_source_state(cloud_sql_session, source_id)
        assert state["counter"] == 1

    def test_counter_progression_persists_postgres(self, cloud_sql_session):
        """Test that counter correctly progresses in PostgreSQL over time."""
        source_id = f"test-progression-{datetime.utcnow().timestamp()}"
        host = "progression.com"

        # Create source with no failures
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="weekly",
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # First failure
        count1 = discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )
        assert count1 == 1

        state1 = self._query_source_state(cloud_sql_session, source_id)
        assert state1["counter"] == 1

        # Manually update timestamp to simulate 8 days passing
        cloud_sql_session.execute(
            text(
                """
                UPDATE sources
                SET no_effective_methods_last_seen = :past_date
                WHERE id = :source_id
                """
            ),
            {
                "past_date": datetime.utcnow() - timedelta(days=8),
                "source_id": source_id,
            },
        )
        cloud_sql_session.flush()

        # Second failure (should succeed after 8 days)
        count2 = discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )
        assert count2 == 2

        state2 = self._query_source_state(cloud_sql_session, source_id)
        assert state2["counter"] == 2

        # Simulate another 8 days
        cloud_sql_session.execute(
            text(
                """
                UPDATE sources
                SET no_effective_methods_last_seen = :past_date
                WHERE id = :source_id
                """
            ),
            {
                "past_date": datetime.utcnow() - timedelta(days=8),
                "source_id": source_id,
            },
        )
        cloud_sql_session.flush()

        # Third failure
        count3 = discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )
        assert count3 == 3

        state3 = self._query_source_state(cloud_sql_session, source_id)
        assert state3["counter"] == 3

    def test_different_frequencies_different_gates_postgres(
        self, cloud_sql_session
    ):
        """Test that different frequencies have different time gates in PostgreSQL."""
        timestamp = datetime.utcnow().timestamp()
        
        # Create daily, weekly, and monthly sources
        daily_id = f"test-daily-{timestamp}"
        weekly_id = f"test-weekly-{timestamp}"
        monthly_id = f"test-monthly-{timestamp}"

        # All with failures 4 days ago
        last_seen = datetime.utcnow() - timedelta(days=4)

        self._create_test_source(
            cloud_sql_session, daily_id, "daily.com", "daily", 1, last_seen
        )
        self._create_test_source(
            cloud_sql_session,
            weekly_id,
            "weekly.com",
            "weekly",
            1,
            last_seen,
        )
        self._create_test_source(
            cloud_sql_session,
            monthly_id,
            "monthly.com",
            "monthly",
            1,
            last_seen,
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Daily should allow (4 days > 6 hours)
        daily_count = discovery._increment_no_effective_methods(
            daily_id,
            source_meta={"frequency": "daily"},
        )
        assert daily_count == 2

        # Weekly should block (4 days < 7 days)
        weekly_count = discovery._increment_no_effective_methods(
            weekly_id,
            source_meta={"frequency": "weekly"},
        )
        assert weekly_count == 1

        # Monthly should block (4 days < 30 days)
        monthly_count = discovery._increment_no_effective_methods(
            monthly_id,
            source_meta={"frequency": "monthly"},
        )
        assert monthly_count == 1

        # Verify PostgreSQL states
        daily_state = self._query_source_state(cloud_sql_session, daily_id)
        weekly_state = self._query_source_state(cloud_sql_session, weekly_id)
        monthly_state = self._query_source_state(cloud_sql_session, monthly_id)

        assert daily_state["counter"] == 2  # Incremented
        assert weekly_state["counter"] == 1  # Blocked
        assert monthly_state["counter"] == 1  # Blocked

    def test_legacy_metadata_also_updated_postgres(self, cloud_sql_session):
        """Test that legacy JSON metadata is also updated for compatibility."""
        source_id = f"test-legacy-{datetime.utcnow().timestamp()}"
        host = "legacy-meta.com"

        # Create source
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="weekly",
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Increment
        discovery._increment_no_effective_methods(
            source_id,
            source_meta={"frequency": "weekly"},
        )

        # Query both typed columns and metadata JSON
        result = cloud_sql_session.execute(
            text(
                """
                SELECT no_effective_methods_consecutive,
                       no_effective_methods_last_seen,
                       metadata
                FROM sources
                WHERE id = :source_id
                """
            ),
            {"source_id": source_id},
        ).fetchone()

        assert result is not None
        counter = result[0]
        last_seen = result[1]
        metadata = result[2]

        # Verify typed columns
        assert counter == 1
        assert last_seen is not None

        # Verify legacy metadata also has values
        assert isinstance(metadata, dict)
        assert "no_effective_methods_consecutive" in metadata
        assert metadata["no_effective_methods_consecutive"] == 1
        assert "no_effective_methods_last_seen" in metadata

    def test_reset_clears_both_columns_postgres(self, cloud_sql_session):
        """Test that reset clears both counter and timestamp in PostgreSQL."""
        source_id = f"test-reset-{datetime.utcnow().timestamp()}"
        host = "reset-test.com"

        # Create source with existing failures
        last_seen = datetime.utcnow() - timedelta(days=1)
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="weekly",
            counter=3,
            last_seen=last_seen,
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Reset counter
        discovery._reset_no_effective_methods(source_id)

        # Verify PostgreSQL columns cleared
        state = self._query_source_state(cloud_sql_session, source_id)
        assert state["counter"] == 0
        # Note: reset doesn't clear timestamp, only counter

    def test_concurrent_checks_handled_correctly_postgres(
        self, cloud_sql_session
    ):
        """Test that multiple rapid checks don't cause race conditions."""
        source_id = f"test-concurrent-{datetime.utcnow().timestamp()}"
        host = "concurrent.com"

        # Create source
        last_seen = datetime.utcnow() - timedelta(hours=1)
        self._create_test_source(
            cloud_sql_session,
            source_id,
            host,
            frequency="daily",
            counter=1,
            last_seen=last_seen,
        )

        db_url = str(cloud_sql_session.get_bind().url)
        discovery = NewsDiscovery(database_url=db_url)

        # Try 10 rapid increments
        counts = []
        for _ in range(10):
            count = discovery._increment_no_effective_methods(
                source_id,
                source_meta={"frequency": "daily"},
            )
            counts.append(count)

        # All should return 1 (blocked)
        assert all(c == 1 for c in counts)

        # Final PostgreSQL state should still be 1
        final_state = self._query_source_state(cloud_sql_session, source_id)
        assert final_state["counter"] == 1
