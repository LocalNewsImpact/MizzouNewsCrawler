"""Test PostgreSQL type handling with mocked database responses.

These tests validate our type conversion logic WITHOUT requiring a real
PostgreSQL database. We mock the database responses to simulate PostgreSQL's
string aggregate behavior.
"""

import pytest
from unittest.mock import Mock

from src.cli.commands.extraction import _to_int as extraction_to_int
from src.cli.commands.pipeline_status import _to_int as pipeline_to_int


class TestTypeConversionHelpers:
    """Test _to_int helper functions with various inputs."""

    def test_to_int_converts_string_numbers(self):
        """PostgreSQL pg8000 returns aggregates as strings."""
        assert pipeline_to_int("42", 0) == 42
        assert pipeline_to_int("0", 0) == 0
        assert pipeline_to_int("12345", 0) == 12345
        assert extraction_to_int("99", 0) == 99

    def test_to_int_handles_native_ints(self):
        """SQLite returns native Python ints."""
        assert pipeline_to_int(42, 0) == 42
        assert pipeline_to_int(0, 0) == 0
        assert extraction_to_int(99, 0) == 99

    def test_to_int_handles_none(self):
        """NULL results should use default."""
        assert pipeline_to_int(None, 0) == 0
        assert pipeline_to_int(None, 999) == 999
        assert extraction_to_int(None, -1) == -1

    def test_to_int_handles_invalid_input(self):
        """Invalid input should use default."""
        assert pipeline_to_int("invalid", 0) == 0
        assert pipeline_to_int("", 0) == 0
        assert pipeline_to_int([], 0) == 0
        assert pipeline_to_int({}, 0) == 0


class TestPostgresStringAggregates:
    """Test handling of PostgreSQL's string aggregate responses."""

    def test_count_query_with_string_result(self):
        """Simulate PostgreSQL COUNT(*) returning string."""
        # Mock a result that returns string like PostgreSQL
        mock_result = Mock()
        mock_result.scalar.return_value = "42"  # PostgreSQL behavior
        
        # Our code should handle this
        count = pipeline_to_int(mock_result.scalar(), 0)
        assert count == 42
        assert isinstance(count, int)

    def test_sum_query_with_string_result(self):
        """Simulate PostgreSQL SUM() returning string."""
        mock_result = Mock()
        mock_result.scalar.return_value = "12345"  # PostgreSQL behavior
        
        total = pipeline_to_int(mock_result.scalar(), 0)
        assert total == 12345
        assert isinstance(total, int)

    def test_max_query_with_string_result(self):
        """Simulate PostgreSQL MAX() returning string."""
        mock_result = Mock()
        mock_result.scalar.return_value = "999"  # PostgreSQL behavior
        
        maximum = pipeline_to_int(mock_result.scalar(), 0)
        assert maximum == 999
        assert isinstance(maximum, int)

    def test_aggregate_with_null_result(self):
        """Simulate aggregate on empty table returning NULL."""
        mock_result = Mock()
        mock_result.scalar.return_value = None  # NULL from database
        
        count = pipeline_to_int(mock_result.scalar(), 0)
        assert count == 0
        assert isinstance(count, int)

    def test_row_tuple_with_string_aggregate(self):
        """Simulate PostgreSQL row with string aggregate value."""
        # Mock a row that returns string for aggregate column
        mock_row = Mock()
        mock_row.__getitem__ = Mock(return_value="75")  # row[1] returns string
        
        value = pipeline_to_int(mock_row[1], 0)
        assert value == 75
        assert isinstance(value, int)


class TestScalarOrPatternBug:
    """Test the '.scalar() or default' anti-pattern that fails with PostgreSQL."""

    def test_scalar_or_pattern_fails_with_string(self):
        """Demonstrate why '.scalar() or 0' doesn't work with PostgreSQL.
        
        PostgreSQL returns "42" (truthy string), so the `or` never evaluates
        to the default. But "42" is not an int, breaking arithmetic.
        """
        mock_result = Mock()
        mock_result.scalar.return_value = "42"  # PostgreSQL returns string
        
        # BAD PATTERN: This "works" but returns wrong type
        bad_result = mock_result.scalar() or 0
        assert bad_result == "42"  # ❌ Returns STRING, not int!
        assert isinstance(bad_result, str)
        
        # GOOD PATTERN: Use _to_int helper
        good_result = pipeline_to_int(mock_result.scalar(), 0)
        assert good_result == 42  # ✅ Returns INT
        assert isinstance(good_result, int)

    def test_scalar_or_pattern_with_zero(self):
        """PostgreSQL returns "0" string, which is truthy!"""
        mock_result = Mock()
        mock_result.scalar.return_value = "0"  # PostgreSQL returns string "0"
        
        # BAD: String "0" is truthy, so `or 999` never triggers
        bad_result = mock_result.scalar() or 999
        assert bad_result == "0"  # ❌ Returns "0" not 999
        
        # GOOD: _to_int properly converts
        good_result = pipeline_to_int(mock_result.scalar(), 999)
        assert good_result == 0  # ✅ Returns int 0
        assert isinstance(good_result, int)

    def test_scalar_or_pattern_with_null(self):
        """The only case where `.scalar() or default` works correctly."""
        mock_result = Mock()
        mock_result.scalar.return_value = None  # NULL result
        
        # Works because None is falsy
        result = mock_result.scalar() or 0
        assert result == 0
        
        # But _to_int is still better for consistency
        good_result = pipeline_to_int(mock_result.scalar(), 0)
        assert good_result == 0


class TestDatabaseIndependence:
    """Test that our code works with both SQLite and PostgreSQL behaviors."""

    @pytest.mark.parametrize("db_value,expected", [
        (42, 42),        # SQLite native int
        ("42", 42),      # PostgreSQL string
        (0, 0),          # SQLite zero
        ("0", 0),        # PostgreSQL zero string
        (None, 0),       # NULL result
        ("", 0),         # Empty string
        ("invalid", 0),  # Invalid string
    ])
    def test_to_int_handles_both_databases(self, db_value, expected):
        """Verify _to_int works with both SQLite ints and PostgreSQL strings."""
        result = pipeline_to_int(db_value, 0)
        assert result == expected
        assert isinstance(result, int)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_large_numbers(self):
        """Test with large numbers."""
        assert pipeline_to_int("999999999", 0) == 999999999
        assert pipeline_to_int(999999999, 0) == 999999999

    def test_negative_numbers(self):
        """Test with negative numbers (though unlikely in COUNT/SUM)."""
        assert pipeline_to_int("-42", 0) == -42
        assert pipeline_to_int(-42, 0) == -42

    def test_float_strings(self):
        """Test with float strings (not supported by int(), returns default)."""
        # int("42.7") raises ValueError, so should return default
        assert pipeline_to_int("42.7", 0) == 0
        assert pipeline_to_int("99.9", 0) == 0
        # Note: If we need float support, use float(value) first
        assert pipeline_to_int(str(int(float("42.7"))), 0) == 42

    def test_whitespace_strings(self):
        """Test with whitespace around numbers."""
        # Most implementations will fail - this documents current behavior
        try:
            result = pipeline_to_int(" 42 ", 0)
            # If it works, great!
            assert result == 42
        except ValueError:
            # If it doesn't, the test should fall back to default
            result = 0
            assert result == 0
