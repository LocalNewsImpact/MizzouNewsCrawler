"""
Test suite for RSS transient failure tracking.

Tests the feature that tracks repeated "transient" errors (429, 403, 5xx) over time
and marks RSS as missing when they exceed a threshold within a rolling window.
This prevents wasting resources on feeds that are permanently blocked but
misreported by servers as transient errors.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from src.crawler.discovery import (
    RSS_TRANSIENT_THRESHOLD,
    RSS_TRANSIENT_WINDOW_DAYS,
    NewsDiscovery,
)
from src.models import Source
from src.models.database import DatabaseManager


def _read_source_meta(db_url: str, source_id: str) -> dict:
    """Helper to read source metadata from database."""
    dbm = DatabaseManager(database_url=db_url)
    try:
        with dbm.engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(
                text("SELECT metadata FROM sources WHERE id = :id"),
                {"id": source_id},
            ).fetchone()
        if result and result[0]:
            return json.loads(result[0])
        return {}
    finally:
        dbm.close()


class TestTransientFailureTracking:
    """Test tracking of repeated transient RSS errors."""

    def test_single_transient_failure_doesnt_mark_missing(self, tmp_path):
        """Test that a single 429 error doesn't mark RSS as permanently missing."""
        db_file = tmp_path / "test_single_transient.db"
        db_url = f"sqlite:///{db_file}"

        # Create source
        dbm = DatabaseManager(database_url=db_url)
        source = Source(
            id="test-source-single",
            host="example.com",
            host_norm="example.com",
            canonical_name="Example Com",
            meta={},
        )
        dbm.session.add(source)
        dbm.session.commit()
        dbm.close()

        discovery = NewsDiscovery(database_url=db_url)

        # Mock RSS to return 429
        def mock_rss_429(*args, **kwargs):
            return [], {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 1,
                "last_transient_status": 429,
            }

        with patch.object(discovery, "discover_with_rss_feeds", mock_rss_429):
            with patch.object(
                discovery, "discover_with_newspaper4k", lambda *a, **k: []
            ):
                source_row = pd.Series(
                    {
                        "id": "test-source-single",
                        "name": "Example Com",
                        "url": "https://example.com",
                        "metadata": json.dumps({}),
                    }
                )
                discovery.process_source(
                    source_row, dataset_label="test", operation_id=None
                )

        # Check metadata
        meta = _read_source_meta(db_url, "test-source-single")

        # Should have transient failure recorded
        assert "rss_transient_failures" in meta
        assert len(meta["rss_transient_failures"]) == 1
        assert meta["rss_transient_failures"][0]["status"] == 429

        # Should NOT be marked as missing yet
        assert meta.get("rss_missing") is None

        # Should have rss_last_failed timestamp
        assert "rss_last_failed" in meta

    def test_threshold_reached_marks_missing(self, tmp_path):
        """Test that 5 transient failures in 7 days marks RSS as missing."""
        db_file = tmp_path / "test_threshold.db"
        db_url = f"sqlite:///{db_file}"

        # Create source
        dbm = DatabaseManager(database_url=db_url)
        source = Source(
            id="test-source-threshold",
            host="blocked.example.com",
            host_norm="blocked.example.com",
            canonical_name="Blocked Example",
            meta={},
        )
        dbm.session.add(source)
        dbm.session.commit()
        dbm.close()

        discovery = NewsDiscovery(database_url=db_url)

        # Mock RSS to return 429
        def mock_rss_429(*args, **kwargs):
            return [], {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 1,
                "last_transient_status": 429,
            }

        source_row = pd.Series(
            {
                "id": "test-source-threshold",
                "name": "Blocked Example",
                "url": "https://blocked.example.com",
                "metadata": json.dumps({}),
            }
        )

        with patch.object(discovery, "discover_with_rss_feeds", mock_rss_429):
            with patch.object(
                discovery, "discover_with_newspaper4k", lambda *a, **k: []
            ):
                # Simulate RSS_TRANSIENT_THRESHOLD failures
                for i in range(RSS_TRANSIENT_THRESHOLD):
                    discovery.process_source(
                        source_row, dataset_label="test", operation_id=None
                    )
                    meta = _read_source_meta(db_url, "test-source-threshold")

                    # Check progress
                    assert len(meta["rss_transient_failures"]) == i + 1

                    if i < RSS_TRANSIENT_THRESHOLD - 1:
                        # Not yet at threshold
                        assert meta.get("rss_missing") is None
                    else:
                        # Threshold reached!
                        assert "rss_missing" in meta
                        assert meta["rss_missing"] is not None

    def test_rolling_window_expiration(self, tmp_path):
        """Test that old failures outside 7-day window don't count."""
        db_file = tmp_path / "test_rolling_window.db"
        db_url = f"sqlite:///{db_file}"

        # Create source with old transient failures (outside window)
        now = datetime.utcnow()
        old_failure_time = now - timedelta(days=RSS_TRANSIENT_WINDOW_DAYS + 1)

        initial_meta = {
            "rss_transient_failures": [
                {"timestamp": old_failure_time.isoformat(), "status": 429},
                {"timestamp": old_failure_time.isoformat(), "status": 429},
                {"timestamp": old_failure_time.isoformat(), "status": 429},
                {"timestamp": old_failure_time.isoformat(), "status": 429},
            ]
        }

        dbm = DatabaseManager(database_url=db_url)
        source = Source(
            id="test-source-old",
            host="old.example.com",
            host_norm="old.example.com",
            canonical_name="Old Example",
            meta=initial_meta,
        )
        dbm.session.add(source)
        dbm.session.commit()
        dbm.close()

        discovery = NewsDiscovery(database_url=db_url)

        # Mock RSS to return 429
        def mock_rss_429(*args, **kwargs):
            return [], {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 1,
                "last_transient_status": 429,
            }

        source_row = pd.Series(
            {
                "id": "test-source-old",
                "name": "Old Example",
                "url": "https://old.example.com",
                "metadata": json.dumps(initial_meta),
            }
        )

        with patch.object(discovery, "discover_with_rss_feeds", mock_rss_429):
            with patch.object(
                discovery, "discover_with_newspaper4k", lambda *a, **k: []
            ):
                discovery.process_source(
                    source_row, dataset_label="test", operation_id=None
                )

        # Check metadata
        meta = _read_source_meta(db_url, "test-source-old")

        # Old failures should be filtered out, only 1 recent failure
        assert len(meta["rss_transient_failures"]) == 1

        # Should NOT be marked as missing (only 1 in window)
        assert meta.get("rss_missing") is None

    def test_successful_rss_clears_transient_failures(self, tmp_path):
        """Test that successful RSS discovery clears transient failure history."""
        db_file = tmp_path / "test_success_clear.db"
        db_url = f"sqlite:///{db_file}"

        # Create source with existing transient failures
        initial_meta = {
            "rss_transient_failures": [
                {"timestamp": datetime.utcnow().isoformat(), "status": 429},
                {"timestamp": datetime.utcnow().isoformat(), "status": 403},
            ]
        }

        dbm = DatabaseManager(database_url=db_url)
        source = Source(
            id="test-source-success",
            host="success.example.com",
            host_norm="success.example.com",
            canonical_name="Success Example",
            meta=initial_meta,
        )
        dbm.session.add(source)
        dbm.session.commit()
        dbm.close()

        discovery = NewsDiscovery(database_url=db_url)

        # Mock RSS to succeed
        def mock_rss_success(*args, **kwargs):
            return [
                {
                    "url": "https://success.example.com/article1",
                    "source_url": "https://success.example.com",
                    "discovery_method": "rss_feed",
                    "discovered_at": datetime.utcnow().isoformat(),
                    "title": "Test Article",
                    "metadata": {},
                }
            ], {
                "feeds_tried": 1,
                "feeds_successful": 1,
                "network_errors": 0,
                "last_transient_status": None,
            }

        source_row = pd.Series(
            {
                "id": "test-source-success",
                "name": "Success Example",
                "url": "https://success.example.com",
                "metadata": json.dumps(initial_meta),
            }
        )

        with patch.object(discovery, "discover_with_rss_feeds", mock_rss_success):
            with patch.object(
                discovery, "discover_with_newspaper4k", lambda *a, **k: []
            ):
                discovery.process_source(
                    source_row, dataset_label="test", operation_id=None
                )

        # Check metadata
        meta = _read_source_meta(db_url, "test-source-success")

        # Transient failures should be cleared
        assert meta.get("rss_transient_failures", []) == []

        # Should not be marked as missing
        assert meta.get("rss_missing") is None

        # Should have last_successful_method set
        assert meta.get("last_successful_method") == "rss_feed"

    def test_different_status_codes_tracked(self, tmp_path):
        """Test that 403, 429, and 5xx all count toward threshold."""
        db_file = tmp_path / "test_status_codes.db"
        db_url = f"sqlite:///{db_file}"

        # Create source
        dbm = DatabaseManager(database_url=db_url)
        source = Source(
            id="test-source-codes",
            host="codes.example.com",
            host_norm="codes.example.com",
            canonical_name="Codes Example",
            meta={},
        )
        dbm.session.add(source)
        dbm.session.commit()
        dbm.close()

        discovery = NewsDiscovery(database_url=db_url)

        source_row = pd.Series(
            {
                "id": "test-source-codes",
                "name": "Codes Example",
                "url": "https://codes.example.com",
                "metadata": json.dumps({}),
            }
        )

        # Test different status codes
        status_codes = [403, 429, 500, 502, 503]

        with patch.object(discovery, "discover_with_newspaper4k", lambda *a, **k: []):
            for status in status_codes:

                def mock_rss_status(*args, **kwargs):
                    return [], {
                        "feeds_tried": 1,
                        "feeds_successful": 0,
                        "network_errors": 1,
                        "last_transient_status": status,
                    }

                with patch.object(
                    discovery, "discover_with_rss_feeds", mock_rss_status
                ):
                    discovery.process_source(
                        source_row, dataset_label="test", operation_id=None
                    )

        # Check metadata
        meta = _read_source_meta(db_url, "test-source-codes")

        # All 5 failures should be tracked
        assert len(meta["rss_transient_failures"]) == 5

        # Should be marked as missing (threshold reached)
        assert "rss_missing" in meta
        assert meta["rss_missing"] is not None

        # Check that different status codes were recorded
        recorded_statuses = [f["status"] for f in meta["rss_transient_failures"]]
        assert 403 in recorded_statuses
        assert 429 in recorded_statuses
        assert 500 in recorded_statuses

    def test_transient_failure_with_no_status_code(self, tmp_path):
        """Test that transient failures without status codes are still tracked."""
        db_file = tmp_path / "test_no_status.db"
        db_url = f"sqlite:///{db_file}"

        # Create source
        dbm = DatabaseManager(database_url=db_url)
        source = Source(
            id="test-source-no-status",
            host="nostatus.example.com",
            host_norm="nostatus.example.com",
            canonical_name="No Status Example",
            meta={},
        )
        dbm.session.add(source)
        dbm.session.commit()
        dbm.close()

        discovery = NewsDiscovery(database_url=db_url)

        # Mock RSS to return network error without status
        def mock_rss_no_status(*args, **kwargs):
            return [], {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 1,
                "last_transient_status": None,
            }

        source_row = pd.Series(
            {
                "id": "test-source-no-status",
                "name": "No Status Example",
                "url": "https://nostatus.example.com",
                "metadata": json.dumps({}),
            }
        )

        with patch.object(discovery, "discover_with_rss_feeds", mock_rss_no_status):
            with patch.object(
                discovery, "discover_with_newspaper4k", lambda *a, **k: []
            ):
                discovery.process_source(
                    source_row, dataset_label="test", operation_id=None
                )

        # Check metadata
        meta = _read_source_meta(db_url, "test-source-no-status")

        # Should still track the failure
        assert "rss_transient_failures" in meta
        assert len(meta["rss_transient_failures"]) == 1

        # Failure record should have timestamp but no status
        assert "timestamp" in meta["rss_transient_failures"][0]
        assert "status" not in meta["rss_transient_failures"][0]

    def test_mixed_transient_and_consecutive_failures(self, tmp_path):
        """Test that transient and consecutive failures are tracked independently."""
        db_file = tmp_path / "test_mixed.db"
        db_url = f"sqlite:///{db_file}"

        # Create source
        dbm = DatabaseManager(database_url=db_url)
        source = Source(
            id="test-source-mixed",
            host="mixed.example.com",
            host_norm="mixed.example.com",
            canonical_name="Mixed Example",
            meta={},
        )
        dbm.session.add(source)
        dbm.session.commit()
        dbm.close()

        discovery = NewsDiscovery(database_url=db_url)

        source_row = pd.Series(
            {
                "id": "test-source-mixed",
                "name": "Mixed Example",
                "url": "https://mixed.example.com",
                "metadata": json.dumps({}),
            }
        )

        # First: 2 transient failures
        def mock_rss_429(*args, **kwargs):
            return [], {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 1,
                "last_transient_status": 429,
            }

        with patch.object(discovery, "discover_with_rss_feeds", mock_rss_429):
            with patch.object(
                discovery, "discover_with_newspaper4k", lambda *a, **k: []
            ):
                for _ in range(2):
                    discovery.process_source(
                        source_row, dataset_label="test", operation_id=None
                    )

        meta = _read_source_meta(db_url, "test-source-mixed")
        assert len(meta["rss_transient_failures"]) == 2
        assert meta.get("rss_consecutive_failures", 0) == 0  # Transient resets this

        # Then: 2 non-network failures (404, parse error)
        def mock_rss_404(*args, **kwargs):
            return [], {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 0,  # No network errors
                "last_transient_status": None,
            }

        with patch.object(discovery, "discover_with_rss_feeds", mock_rss_404):
            with patch.object(
                discovery, "discover_with_newspaper4k", lambda *a, **k: []
            ):
                for _ in range(2):
                    discovery.process_source(
                        source_row, dataset_label="test", operation_id=None
                    )

        meta = _read_source_meta(db_url, "test-source-mixed")

        # Transient failures should still be 2
        assert len(meta["rss_transient_failures"]) == 2

        # Consecutive failures should be incremented
        assert meta.get("rss_consecutive_failures", 0) == 2

        # Not marked as missing yet (need 3 consecutive or 5 transient)
        assert meta.get("rss_missing") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
