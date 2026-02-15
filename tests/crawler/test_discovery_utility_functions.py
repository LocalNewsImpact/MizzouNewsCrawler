"""Tests for discovery.py utility functions to increase coverage."""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import time as time_module

from src.crawler.discovery import (
    _safe_struct_time_to_datetime,
    _coerce_feed_entry,
    get_sources_from_db,
    RSS_MISSING_THRESHOLD,
    RSS_TRANSIENT_THRESHOLD,
    RSS_TRANSIENT_WINDOW_DAYS,
)


class TestSafeStructTimeToDatetime:
    """Test _safe_struct_time_to_datetime function."""

    def test_converts_struct_time(self):
        """Should convert time.struct_time to datetime."""
        st = time_module.struct_time((2024, 1, 15, 10, 30, 0, 0, 15, 0))
        result = _safe_struct_time_to_datetime(st)
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_converts_tuple(self):
        """Should convert tuple to datetime."""
        tup = (2024, 1, 15, 10, 30, 0)
        result = _safe_struct_time_to_datetime(tup)
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_handles_none(self):
        """Should return None for None input."""
        assert _safe_struct_time_to_datetime(None) is None

    def test_handles_invalid_input(self):
        """Should return None for invalid input."""
        assert _safe_struct_time_to_datetime("not a time") is None
        assert _safe_struct_time_to_datetime(12345) is None
        assert _safe_struct_time_to_datetime({}) is None


class TestCoerceFeedEntry:
    """Test _coerce_feed_entry function."""

    def test_normalizes_basic_entry(self):
        """Should normalize a basic feed entry."""
        raw = {
            "link": "https://example.com/story",
            "title": "Test Story",
            "summary": "Test summary",
        }
        result = _coerce_feed_entry(raw)
        assert result["url"] == "https://example.com/story"
        assert result["title"] == "Test Story"
        assert result["summary"] == "Test summary"
        assert "publish_date" in result

    def test_handles_list_title(self):
        """Should handle title as list."""
        raw = {
            "link": "https://example.com/story",
            "title": ["Title 1", "Title 2"],
        }
        result = _coerce_feed_entry(raw)
        assert "Title 1" in result["title"]
        assert "Title 2" in result["title"]

    def test_handles_empty_list_title(self):
        """Should handle empty list title."""
        raw = {
            "link": "https://example.com/story",
            "title": [],
        }
        result = _coerce_feed_entry(raw)
        assert result["title"] == ""

    def test_handles_struct_time_published(self):
        """Should convert struct_time published_parsed to datetime."""
        st = time_module.struct_time((2024, 1, 15, 10, 30, 0, 0, 15, 0))
        raw = {
            "link": "https://example.com/story",
            "published_parsed": st,
        }
        result = _coerce_feed_entry(raw)
        assert isinstance(result["publish_date"], datetime)

    def test_handles_string_published(self):
        """Should keep string published as-is."""
        raw = {
            "link": "https://example.com/story",
            "published": "2024-01-15T10:30:00Z",
        }
        result = _coerce_feed_entry(raw)
        assert result["published"] == "2024-01-15T10:30:00Z"

    def test_handles_missing_fields(self):
        """Should handle missing optional fields."""
        raw = {"link": "https://example.com/story"}
        result = _coerce_feed_entry(raw)
        assert result["url"] == "https://example.com/story"
        assert result["title"] == ""
        assert result["summary"] == ""


class TestGetSourcesFromDb:
    """Test get_sources_from_db function."""

    @patch("src.crawler.discovery.safe_session_execute")
    def test_gets_all_sources_no_filter(self, mock_execute):
        """Should get all active sources when no filters."""
        # Setup mock database manager
        mock_db = Mock()
        mock_db.engine = Mock()
        mock_db.session = Mock()

        # Setup mock result
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            {"id": 1, "host": "example.com", "canonical_name": "Example News"},
            {"id": 2, "host": "test.com", "canonical_name": "Test News"},
        ]
        mock_execute.return_value = mock_result

        sources = get_sources_from_db(mock_db)

        assert len(sources) == 2
        assert sources[0]["host"] == "example.com"
        assert sources[0]["url"] == "https://example.com"
        assert sources[1]["host"] == "test.com"

    @patch("src.crawler.discovery.safe_session_execute")
    def test_filters_by_dataset(self, mock_execute):
        """Should filter sources by dataset_id."""
        mock_db = Mock()
        mock_db.engine = Mock()
        mock_db.session = Mock()

        mock_result = Mock()
        mock_result.fetchall.return_value = [
            {
                "id": 1,
                "host": "example.com",
                "canonical_name": "Example News",
            },
        ]
        mock_execute.return_value = mock_result

        sources = get_sources_from_db(mock_db, dataset_id="test-dataset")

        assert len(sources) == 1
        mock_execute.assert_called_once()

    @patch("src.crawler.discovery.safe_session_execute")
    def test_applies_limit(self, mock_execute):
        """Should limit number of sources returned."""
        mock_db = Mock()
        mock_db.engine = Mock()
        mock_db.session = Mock()

        mock_result = Mock()
        mock_result.fetchall.return_value = [
            {"id": 1, "host": "example.com", "canonical_name": "Example News"},
        ]
        mock_execute.return_value = mock_result

        sources = get_sources_from_db(mock_db, limit=1)

        assert len(sources) == 1


class TestRssThresholds:
    """Test RSS threshold constants are defined."""

    def test_thresholds_defined(self):
        """Should have RSS threshold constants defined."""
        assert RSS_MISSING_THRESHOLD == 3
        assert RSS_TRANSIENT_THRESHOLD == 5
        assert RSS_TRANSIENT_WINDOW_DAYS == 7
