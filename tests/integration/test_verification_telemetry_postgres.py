"""Integration tests for verification telemetry with PostgreSQL.

These tests verify the database schema and that telemetry writes work correctly.
"""

import json
import os

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.integration
@pytest.mark.postgres
def test_record_verification_batch_writes_to_database():
    """Test that record_verification_batch writes to PostgreSQL."""
    from src.telemetry.store import TelemetryStore
    from src.utils.telemetry import create_telemetry_system
    
    database_url = os.environ["TEST_DATABASE_URL"]
    
    # Create synchronous store for testing
    store = TelemetryStore(database=database_url, async_writes=False)
    tracker = create_telemetry_system(database_url=database_url, store=store)
    
    tracker.record_verification_batch(
        job_name="test_job",
        batch_size=10,
        verified_articles=7,
        verified_non_articles=2,
        verification_errors=1,
        total_processed=9,
        batch_time_seconds=5.5,
        avg_verification_time_ms=550.0,
        total_time_ms=4950.0,
        sources_processed=["source1", "source2"],
    )
    
    # Verify with separate connection to avoid transaction issues
    engine = create_engine(database_url)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT * FROM verification_telemetry "
                "ORDER BY created_at DESC LIMIT 1"
            )
        )
        row = result.fetchone()
    
    assert row is not None
    assert row.job_name == "test_job"
    assert row.batch_size == 10
    assert row.verified_articles == 7
    assert row.verified_non_articles == 2
    sources = json.loads(row.sources_processed)
    assert sources == ["source1", "source2"]


@pytest.mark.integration
@pytest.mark.postgres
def test_record_verification_batch_multiple_batches():
    """Test that multiple batches are recorded correctly."""
    from src.telemetry.store import TelemetryStore
    from src.utils.telemetry import create_telemetry_system
    
    database_url = os.environ["TEST_DATABASE_URL"]
    
    # Create synchronous store for testing
    store = TelemetryStore(database=database_url, async_writes=False)
    tracker = create_telemetry_system(database_url=database_url, store=store)
    
    for i in range(3):
        tracker.record_verification_batch(
            job_name=f"batch_{i}",
            batch_size=5,
            verified_articles=i + 1,
            verified_non_articles=4 - i,
            verification_errors=0,
            total_processed=5,
            batch_time_seconds=1.0,
            avg_verification_time_ms=200.0,
            total_time_ms=1000.0,
            sources_processed=[f"source_{i}"],
        )
    
    # Verify all batches were written with separate connection
    engine = create_engine(database_url)
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) FROM verification_telemetry")
        )
        count = result.fetchone()[0]
    
    assert count >= 3


@pytest.mark.integration
@pytest.mark.postgres
def test_record_verification_batch_index_exists():
    """Test that required indexes exist."""
    database_url = os.environ["TEST_DATABASE_URL"]
    
    engine = create_engine(database_url)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'verification_telemetry' "
                "AND indexname = 'idx_verification_telemetry_timestamp'"
            )
        )
        assert result.fetchone() is not None
