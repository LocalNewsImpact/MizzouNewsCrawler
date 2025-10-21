"""Tests for discovery outcome telemetry writers."""

from __future__ import annotations

import pytest

from src.telemetry.store import TelemetryStore
from src.utils.discovery_outcomes import DiscoveryOutcome, DiscoveryResult
from src.utils.telemetry import OperationTracker


@pytest.fixture
def tracker_with_store(tmp_path):
    """Provide an operation tracker backed by a temporary telemetry store."""
    db_path = tmp_path / "telemetry_discovery.db"
    db_uri = f"sqlite:///{db_path}"
    store = TelemetryStore(database=db_uri, async_writes=False)
    tracker = OperationTracker(store=store, database_url=db_uri)
    try:
        yield tracker, store
    finally:
        store.shutdown(wait=True)


def test_discovery_outcome_persists_without_sources_table(tracker_with_store, caplog):
    """Test that discovery outcomes can be persisted without sources table."""
    tracker, store = tracker_with_store

    result = DiscoveryResult(
        outcome=DiscoveryOutcome.NEW_ARTICLES_FOUND,
        articles_found=5,
        articles_new=3,
        metadata={"methods_attempted": ["rss"]},
    )

    # Record discovery outcome (should succeed even without sources table)
    tracker.record_discovery_outcome(
        operation_id="op-1",
        source_id="source-123",
        source_name="Example Source",
        source_url="https://example.com",
        discovery_result=result,
    )

    # Verify outcome was persisted by querying the store
    # Since this is an async store, we need to flush writes
    store.flush()
    
    # Verify no errors occurred (check that no error logs were emitted)
    assert not any(
        "Failed to record discovery outcome" in message
        for message in caplog.messages
    )

    with store.connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT source_id, outcome, is_success FROM discovery_outcomes"
            )
            row = cursor.fetchone()
        finally:
            cursor.close()

    assert row == ("source-123", "new_articles_found", 1)
