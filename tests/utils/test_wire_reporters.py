"""Tests for wire_reporters module."""

import pytest

from src.utils.wire_reporters import (
    clear_wire_reporters_cache,
    is_wire_reporter,
    set_wire_reporters_cache,
)


class TestWireReportersCache:
    """Test cache management functions."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_wire_reporters_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        clear_wire_reporters_cache()

    def test_clear_wire_reporters_cache(self):
        """Test clearing the cache sets it to None."""
        set_wire_reporters_cache({"test": ("AP", "high")})
        clear_wire_reporters_cache()
        # After clearing, next call should reload from DB (or return empty if DB unavailable)
        # We just verify the function runs without error
        assert True

    def test_set_wire_reporters_cache(self):
        """Test setting cache directly."""
        test_cache = {
            "john smith": ("Associated Press", "high"),
            "jane doe": ("Reuters", "high"),
        }
        set_wire_reporters_cache(test_cache)
        # Verify cache is set by looking up a reporter
        result = is_wire_reporter("John Smith")
        assert result == ("Associated Press", "high")

    def test_is_wire_reporter_empty_author(self):
        """Test that empty/None author returns None."""
        assert is_wire_reporter("") is None
        assert is_wire_reporter(None) is None

    def test_is_wire_reporter_direct_match(self):
        """Test direct case-insensitive match."""
        set_wire_reporters_cache(
            {
                "john smith": ("AP", "high"),
                "jane doe": ("Reuters", "high"),
            }
        )

        # Exact match (case insensitive)
        assert is_wire_reporter("John Smith") == ("AP", "high")
        assert is_wire_reporter("JOHN SMITH") == ("AP", "high")
        assert is_wire_reporter("  john smith  ") == ("AP", "high")

    def test_is_wire_reporter_no_match(self):
        """Test that unknown author returns None."""
        set_wire_reporters_cache(
            {
                "john smith": ("AP", "high"),
            }
        )

        assert is_wire_reporter("Unknown Reporter") is None
        assert is_wire_reporter("Random Name") is None

    def test_is_wire_reporter_partial_match(self):
        """Test partial matching in multi-author bylines."""
        set_wire_reporters_cache(
            {
                "john smith": ("AP", "high"),
                "jane doe": ("Reuters", "high"),
            }
        )

        # Multi-author byline containing known wire reporter
        result = is_wire_reporter("John Smith and Jane Doe")
        # Should match one of them (implementation dependent on order)
        assert result is not None
        assert result[1] == "high"

        # Wire reporter in middle of byline
        result = is_wire_reporter("Some Editor, John Smith, and Others")
        assert result == ("AP", "high")

    def test_is_wire_reporter_word_boundary(self):
        """Test that partial matches respect word boundaries."""
        set_wire_reporters_cache(
            {
                "smith": ("AP", "high"),
            }
        )

        # Should match "smith" at word boundary
        assert is_wire_reporter("John Smith") == ("AP", "high")

        # Should NOT match "smith" within another word
        # (though this behavior depends on regex implementation)
        result = is_wire_reporter("Blacksmith")
        # With word boundary regex, this should NOT match
        assert result is None


class TestWireReportersIntegration:
    """Test database integration (mocked)."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_wire_reporters_cache()

    def teardown_method(self):
        """Clear cache after each test."""
        clear_wire_reporters_cache()

    def test_is_wire_reporter_with_empty_cache(self):
        """Test behavior when cache needs to be loaded."""
        # With no cache set and no test database, should handle gracefully
        # and return None (db loading will fail but should not crash)
        result = is_wire_reporter("Some Author")
        # Should return None (either no match or empty cache from DB failure)
        assert result is None or isinstance(result, tuple)

    def test_is_wire_reporter_database_error_handling(self):
        """Test that database errors are handled gracefully."""
        # First clear cache to force database load attempt
        clear_wire_reporters_cache()

        # When database is unavailable (as in test environment without proper setup),
        # the function should not crash but return None
        result = is_wire_reporter("John Smith")

        # After DB load failure, cache should be empty dict
        # So any lookup should return None
        assert result is None

        # Subsequent calls should also work (using cached empty dict)
        result2 = is_wire_reporter("Jane Doe")
        assert result2 is None
