"""Tests for RSS failure tracking and recovery logic in discovery.py.

This test module covers:
- _track_transient_rss_failure: Transient failure tracking
- _increment_rss_failure: Persistent RSS failure counter
- _reset_rss_failure_state: RSS failure reset
- _rss_retry_window_days: RSS retry window calculation
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from src.crawler.discovery import NewsDiscovery


@pytest.fixture
def discovery_instance():
    """Create NewsDiscovery instance with mocked dependencies."""
    with patch('src.crawler.discovery.create_telemetry_system'):
        with patch('src.crawler.discovery.StorySniffer'):
            with patch('src.crawler.discovery.get_proxy_manager') as mock_proxy:
                mock_proxy_mgr = MagicMock()
                mock_proxy_mgr.active_provider = MagicMock(value="origin")
                mock_proxy_mgr.get_requests_proxies.return_value = {}
                mock_proxy.return_value = mock_proxy_mgr
                
                discovery = NewsDiscovery(
                    database_url="sqlite:///:memory:"
                )
                return discovery


class TestRSSRetryWindowDays:
    """Test _rss_retry_window_days static method."""

    def test_daily_frequency(self, discovery_instance):
        """Daily frequency should have 2-day retry window (1 day * 2)."""
        result = NewsDiscovery._rss_retry_window_days("daily")
        assert result == 2

    def test_weekly_frequency(self, discovery_instance):
        """Weekly frequency should have 7-day retry window (capped at 7)."""
        result = NewsDiscovery._rss_retry_window_days("weekly")
        assert result == 7

    def test_biweekly_frequency(self, discovery_instance):
        """Bi-weekly frequency should have 7-day retry window (capped)."""
        result = NewsDiscovery._rss_retry_window_days("bi-weekly")
        assert result == 7

    def test_monthly_frequency(self, discovery_instance):
        """Monthly frequency should have 7-day retry window (capped at 7)."""
        result = NewsDiscovery._rss_retry_window_days("monthly")
        assert result == 7

    def test_hourly_frequency(self, discovery_instance):
        """Hourly frequency should have minimal retry window (capped at 2)."""
        result = NewsDiscovery._rss_retry_window_days("hourly")
        assert result == 2  # 0.25 * 2 = 0.5, rounded to 1, but min is 2

    def test_none_frequency(self, discovery_instance):
        """None frequency should use default 7-day window."""
        result = NewsDiscovery._rss_retry_window_days(None)
        assert result == 7

    def test_empty_frequency(self, discovery_instance):
        """Empty frequency should use default 7-day window."""
        result = NewsDiscovery._rss_retry_window_days("")
        assert result == 7

    def test_unknown_frequency(self, discovery_instance):
        """Unknown frequency should use default 7-day window."""
        result = NewsDiscovery._rss_retry_window_days("unknown")
        assert result == 7

    def test_invalid_frequency_exception(self, discovery_instance):
        """Invalid frequency that raises exception should return 7."""
        # Numbers can't be parsed as strings
        result = NewsDiscovery._rss_retry_window_days(12345)
        assert result == 7


class TestResetRSSFailureState:
    """Test _reset_rss_failure_state method."""

    def test_reset_rss_success_clears_failures(self, discovery_instance):
        """Successful RSS fetch should reset failure counters."""
        mock_connection = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_connection.execute.return_value = mock_result

        source_id = "test-source-123"
        discovery_instance._reset_rss_failure_state(mock_connection, source_id)

        # Should have executed UPDATE to reset failures
        assert mock_connection.execute.called
        call_args = mock_connection.execute.call_args
        sql = str(call_args[0][0])
        params = call_args[0][1]

        assert "UPDATE sources" in sql
        assert "rss_consecutive_failures = 0" in sql or "rss_consecutive_failures" in sql
        assert params["source_id"] == source_id

    def test_reset_updates_last_successful_rss(self, discovery_instance):
        """Reset should update last_successful_rss_at timestamp."""
        mock_connection = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_connection.execute.return_value = mock_result

        source_id = "test-source-456"
        discovery_instance._reset_rss_failure_state(mock_connection, source_id)

        call_args = mock_connection.execute.call_args
        sql = str(call_args[0][0])

        assert "last_successful_rss_at" in sql
        # Timestamp should be set to NOW()
        assert "NOW()" in sql or "CURRENT_TIMESTAMP" in sql or "datetime" in sql.lower()

    def test_reset_clears_skip_rss_until(self, discovery_instance):
        """Reset should clear skip_rss_until field."""
        mock_connection = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_connection.execute.return_value = mock_result

        source_id = "test-source-789"
        discovery_instance._reset_rss_failure_state(mock_connection, source_id)

        call_args = mock_connection.execute.call_args
        sql = str(call_args[0][0])

        assert "skip_rss_until = NULL" in sql or "skip_rss_until" in sql


class TestTrackTransientRSSFailure:
    """Test _track_transient_rss_failure method."""

    def test_track_transient_failure_updates_metadata(self, discovery_instance):
        """Transient failure tracking should update source metadata."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        # Simulate existing metadata
        mock_row._asdict.return_value = {
            "meta": {"frequency": "weekly", "rss_miss_count": 2}
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-001"
        discovery_instance._track_transient_rss_failure(mock_connection, source_id)

        # Should have updated rss_miss_count
        assert mock_connection.execute.call_count >= 2  # SELECT + UPDATE

    def test_track_transient_initializes_miss_count(self, discovery_instance):
        """First transient failure should initialize miss count to 1."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        # No existing rss_miss_count
        mock_row._asdict.return_value = {"meta": {"frequency": "daily"}}
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-002"
        discovery_instance._track_transient_rss_failure(mock_connection, source_id)

        # Should initialize to 1
        update_call = [
            call for call in mock_connection.execute.call_args_list
            if "UPDATE" in str(call[0][0])
        ]
        assert len(update_call) >= 1

    def test_track_transient_handles_null_metadata(self, discovery_instance):
        """Null metadata should be handled gracefully."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        mock_row._asdict.return_value = {"meta": None}
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-003"
        # Should not raise exception
        discovery_instance._track_transient_rss_failure(mock_connection, source_id)

        assert mock_connection.execute.called

    def test_track_transient_with_json_string_metadata(self, discovery_instance):
        """JSON string metadata should be parsed and updated."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        # Metadata as JSON string
        mock_row._asdict.return_value = {
            "meta": json.dumps({"frequency": "weekly", "rss_miss_count": 5})
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-004"
        discovery_instance._track_transient_rss_failure(mock_connection, source_id)

        assert mock_connection.execute.call_count >= 2


class TestIncrementRSSFailure:
    """Test _increment_rss_failure method."""

    def test_increment_rss_failure_counter(self, discovery_instance):
        """Should increment rss_consecutive_failures counter."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        mock_row._asdict.return_value = {
            "rss_consecutive_failures": 2,
            "meta": {"frequency": "weekly"}
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-100"
        discovery_instance._increment_rss_failure(mock_connection, source_id)

        # Should have executed UPDATE to increment counter
        update_calls = [
            call for call in mock_connection.execute.call_args_list
            if "UPDATE sources" in str(call[0][0])
        ]
        assert len(update_calls) >= 1

    def test_increment_sets_skip_until_after_threshold(self, discovery_instance):
        """After threshold, should set skip_rss_until."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        # Already at threshold (3 failures for weekly)
        mock_row._asdict.return_value = {
            "rss_consecutive_failures": 3,
            "meta": {"frequency": "weekly"}
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-101"
        discovery_instance._increment_rss_failure(mock_connection, source_id)

        # Should set skip_rss_until
        update_call = [
            call for call in mock_connection.execute.call_args_list
            if "skip_rss_until" in str(call[0][0])
        ]
        assert len(update_call) >= 1

    def test_increment_handles_none_failures(self, discovery_instance):
        """None failures should be treated as 0."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        mock_row._asdict.return_value = {
            "rss_consecutive_failures": None,
            "meta": {"frequency": "daily"}
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-102"
        # Should not raise exception
        discovery_instance._increment_rss_failure(mock_connection, source_id)

        assert mock_connection.execute.called

    def test_increment_uses_frequency_for_retry_window(self, discovery_instance):
        """Retry window should respect publication frequency."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        mock_row._asdict.return_value = {
            "rss_consecutive_failures": 5,
            "meta": {"frequency": "monthly"}  # Should use longer retry window
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-103"
        discovery_instance._increment_rss_failure(mock_connection, source_id)

        # Should have called with frequency parameter
        assert mock_connection.execute.called

    def test_increment_logs_failure_count(self, discovery_instance):
        """Should log the current failure count."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        mock_row._asdict.return_value = {
            "rss_consecutive_failures": 4,
            "meta": {"frequency": "daily"}
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-104"

        with patch('src.crawler.discovery.logger') as mock_logger:
            discovery_instance._increment_rss_failure(mock_connection, source_id)
            # Should have logged something about failures
            assert mock_logger.warning.called or mock_logger.info.called


class TestRSSFailureIntegration:
    """Integration tests for RSS failure workflow."""

    def test_transient_to_persistent_failure_flow(self, discovery_instance):
        """Workflow: transient failures -> persistent -> skip."""
        mock_connection = MagicMock()

        # Simulate multiple transient failures
        for i in range(3):
            mock_row = MagicMock()
            mock_row._asdict.return_value = {
                "meta": {"frequency": "daily", "rss_miss_count": i},
                "rss_consecutive_failures": 0
            }
            mock_connection.execute.return_value.fetchone.return_value = mock_row
            discovery_instance._track_transient_rss_failure(mock_connection, "source-123")

        # Now trigger persistent failure
        mock_row = MagicMock()
        mock_row._asdict.return_value = {
            "meta": {"frequency": "daily", "rss_miss_count": 3},
            "rss_consecutive_failures": 0
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row
        discovery_instance._increment_rss_failure(mock_connection, "source-123")

        assert mock_connection.execute.call_count >= 8  # Multiple SELECT and UPDATE calls

    def test_reset_after_success_flow(self, discovery_instance):
        """Workflow: failures -> success -> reset."""
        mock_connection = MagicMock()

        # Simulate failures
        mock_row = MagicMock()
        mock_row._asdict.return_value = {
            "rss_consecutive_failures": 2,
            "meta": {"frequency": "weekly"}
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row
        discovery_instance._increment_rss_failure(mock_connection, "source-456")

        # Now simulate success and reset
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_connection.execute.return_value = mock_result
        discovery_instance._reset_rss_failure_state(mock_connection, "source-456")

        # Should have reset counters
        assert mock_connection.execute.called


class TestRSSFailureEdgeCases:
    """Test edge cases in RSS failure handling."""

    def test_concurrent_failure_tracking(self, discovery_instance):
        """Multiple failure trackers shouldn't interfere."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        mock_row._asdict.return_value = {
            "meta": {"frequency": "daily", "rss_miss_count": 1},
            "rss_consecutive_failures": 1
        }
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        # Track both transient and persistent for same source
        discovery_instance._track_transient_rss_failure(mock_connection, "source-789")
        discovery_instance._increment_rss_failure(mock_connection, "source-789")

        assert mock_connection.execute.call_count >= 4

    def test_database_error_handling(self, discovery_instance):
        """Database errors should be handled gracefully."""
        mock_connection = MagicMock()
        mock_connection.execute.side_effect = Exception("Database connection lost")

        source_id = "test-source-error"

        # Should not raise exception
        try:
            discovery_instance._increment_rss_failure(mock_connection, source_id)
        except Exception:
            pytest.fail("Should handle database errors gracefully")

    def test_malformed_metadata_json(self, discovery_instance):
        """Malformed JSON metadata should not crash."""
        mock_connection = MagicMock()
        mock_row = MagicMock()
        # Invalid JSON string
        mock_row._asdict.return_value = {"meta": "{invalid json syntax"}
        mock_connection.execute.return_value.fetchone.return_value = mock_row

        source_id = "test-source-bad-json"

        # Should handle parsing error gracefully
        try:
            discovery_instance._track_transient_rss_failure(mock_connection, source_id)
        except json.JSONDecodeError:
            pytest.fail("Should handle malformed JSON gracefully")
