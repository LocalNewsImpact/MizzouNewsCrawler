"""Unit tests for feed entry normalization helpers.

Covers _safe_struct_time_to_datetime and _coerce_feed_entry behaviors:
- Title list coercion with mixed types and empties
- Missing fields defaulting to empty strings
- Valid published_parsed sequence conversion
- Invalid sequences (length < 6, non-int components) yielding None
- struct_time handling
- Preservation of internal spacing for list titles (documenting current behavior)
- Missing link returns empty string
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from src.crawler.discovery import _coerce_feed_entry, _safe_struct_time_to_datetime


def test_coerce_feed_entry_title_list_mixed_types():
    raw = {
        "link": "https://example.com/a",
        "title": ["Breaking", "", 42, None, "News"],
    }
    entry = _coerce_feed_entry(raw)
    # None and empty string dropped, numeric converted via str
    assert "title" in entry and entry["title"] == "Breaking 42 News"
    assert "url" in entry and entry["url"] == "https://example.com/a"


def test_coerce_feed_entry_missing_fields_defaults():
    raw = {}  # Completely empty
    entry = _coerce_feed_entry(raw)
    for key in [
        "url",
        "title",
        "summary",
        "published",
        "author",
        "publish_date",
    ]:
        assert key in entry, f"Expected '{key}' key to be populated"
    assert entry.get("url") == ""  # Missing link becomes empty string
    assert entry.get("title") == ""  # Missing title becomes empty string
    assert entry.get("summary") == ""
    assert entry.get("published") == ""
    assert entry.get("author") == ""
    assert entry.get("publish_date") is None


def test_coerce_feed_entry_valid_published_parsed_tuple():
    raw = {
        "link": "https://example.com/b",
        "title": "Sample",
        "published_parsed": (2025, 11, 9, 15, 23, 7, 0, 0, 0),
    }
    entry = _coerce_feed_entry(raw)
    expected = datetime(2025, 11, 9, 15, 23, 7)
    assert entry.get("publish_date") == expected


def test_coerce_feed_entry_invalid_published_parsed_length():
    raw = {"title": "Short", "published_parsed": (2025, 11, 9)}
    entry = _coerce_feed_entry(raw)
    assert entry.get("publish_date") is None


def test_coerce_feed_entry_invalid_published_parsed_non_int():
    raw = {"title": "Bad", "published_parsed": (2025, "11", 9, 10, 11, 12)}
    entry = _coerce_feed_entry(raw)
    assert entry.get("publish_date") is None


def test_safe_struct_time_to_datetime_struct_time():
    ts = time.struct_time((2025, 11, 9, 16, 45, 30, 0, 0, 0))
    dt = _safe_struct_time_to_datetime(ts)
    assert dt == datetime(2025, 11, 9, 16, 45, 30)


def test_safe_struct_time_to_datetime_invalid():
    assert _safe_struct_time_to_datetime(None) is None
    assert _safe_struct_time_to_datetime([2025, 11]) is None  # Too short
    # Non-ints inside first six elements
    assert _safe_struct_time_to_datetime([2025, 11, 9, 10, "x", 30]) is None


def test_coerce_feed_entry_preserves_internal_spaces_in_list_titles():
    raw = {"title": ["  Alpha", "Beta  "]}
    entry = _coerce_feed_entry(raw)
    # Current implementation does not strip individual list elements
    assert entry.get("title") == "  Alpha Beta  "


def test_coerce_feed_entry_missing_link_empty_string():
    raw = {"title": "Example"}
    entry = _coerce_feed_entry(raw)
    assert entry.get("url") == ""


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
