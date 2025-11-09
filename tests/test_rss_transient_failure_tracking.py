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
from tests.helpers.source_state import read_source_state


def _read_source_state(db_url: str, source_id: str) -> dict:
    """Return typed column RSS state for a source (test helper)."""
    dbm = DatabaseManager(database_url=db_url)
    try:
        return read_source_state(dbm.engine, source_id)
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

        state = _read_source_state(db_url, "test-source-single")
        assert len(state.get("rss_transient_failures", [])) == 1
        assert state["rss_transient_failures"][0].get("status") == 429
        assert state.get("rss_missing_at") is None
        assert state.get("rss_last_failed_at") is not None

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
                    state = _read_source_state(db_url, "test-source-threshold")
                    assert len(state.get("rss_transient_failures", [])) == i + 1
                    if i < RSS_TRANSIENT_THRESHOLD - 1:
                        assert state.get("rss_missing_at") is None
                    else:
                        assert state.get("rss_missing_at") is not None

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
        state = _read_source_state(db_url, "test-source-old")
        assert len(state.get("rss_transient_failures", [])) == 1
        assert state.get("rss_missing_at") is None

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
        state = _read_source_state(db_url, "test-source-success")
        assert state.get("rss_transient_failures", []) == []
        assert state.get("rss_missing_at") is None
        assert state.get("last_successful_method") == "rss_feed"

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
        state = _read_source_state(db_url, "test-source-codes")
        assert len(state.get("rss_transient_failures", [])) == 5
        assert state.get("rss_missing_at") is not None
        recorded_statuses = [f.get("status") for f in state["rss_transient_failures"]]
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
        state = _read_source_state(db_url, "test-source-no-status")
        assert len(state.get("rss_transient_failures", [])) == 1
        assert "timestamp" in state["rss_transient_failures"][0]
        assert "status" not in state["rss_transient_failures"][0]

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

        state = _read_source_state(db_url, "test-source-mixed")
        assert len(state.get("rss_transient_failures", [])) == 2
        assert state.get("rss_consecutive_failures", 0) == 0

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

        state = _read_source_state(db_url, "test-source-mixed")
        assert len(state.get("rss_transient_failures", [])) == 2
        assert state.get("rss_consecutive_failures", 0) == 2
        assert state.get("rss_missing_at") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
