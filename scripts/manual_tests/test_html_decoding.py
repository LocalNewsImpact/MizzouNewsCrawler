#!/usr/bin/env python3
"""
Test HTML decoding in byline cleaner

This test verifies that the byline cleaner correctly handles HTML entities
and duplicates in author names.
"""

import pytest
from src.utils.byline_cleaner import BylineCleaner


class TestHTMLDecoding:
    """Test HTML decoding functionality in byline cleaner."""

    def setup_method(self):
        """Set up test instance."""
        self.cleaner = BylineCleaner(enable_telemetry=False)

    def test_apostrophe_decoding(self):
        """Test HTML-encoded apostrophes are decoded correctly."""
        test_cases = [
            ("Emily O&#x27;Leary", "Emily O'Leary"),
            ("Patrick O&#x27;Connor", "Patrick O'Connor"),
            ("Sean O&#x27;Brien", "Sean O'Brien"),
            ("Maria D&#x27;Angelo", "Maria D'Angelo"),
        ]

        for input_name, expected in test_cases:
            result = self.cleaner._clean_author_name(input_name)
            assert result == expected, (
                f"Expected '{expected}', got '{result}' for input '{input_name}'"
            )

    def test_quote_decoding(self):
        """Test HTML-encoded quotes are decoded correctly."""
        test_cases = [
            ("Dr. &quot;Mike&quot; Johnson", 'Dr. "Mike" Johnson'),
            ("&quot;Big Joe&quot; Martinez", '"Big Joe" Martinez'),
            ("Robert &quot;Bob&quot; Smith", 'Robert "Bob" Smith'),
        ]

        for input_name, expected in test_cases:
            result = self.cleaner._clean_author_name(input_name)
            assert result == expected, (
                f"Expected '{expected}', got '{result}' for input '{input_name}'"
            )

    def test_ampersand_decoding(self):
        """Test HTML-encoded ampersands in context."""
        # Note: & in names might be filtered out by other cleaning logic
        input_name = "Smith &amp; Associates"
        result = self.cleaner._clean_author_name(input_name)
        # Just ensure it doesn't crash and removes HTML encoding
        assert "&amp;" not in result
        assert result  # Should produce some result

    def test_clean_byline_with_html_duplicates(self):
        """Test cleaning bylines with HTML-encoded duplicates."""
        test_cases = [
            # Original issue case
            ("Emily O&#x27;Leary, Emily O'Leary", ["Emily O'Leary"]),
            # Multiple HTML encodings
            ('Dr. &quot;John&quot; Smith, Dr. "John" Smith', ['Dr. "John" Smith']),
        ]

        for input_byline, expected in test_cases:
            result = self.cleaner.clean_byline(input_byline)
            assert result == expected, (
                f"Expected {expected}, got {result} for input '{input_byline}'"
            )

    def test_regression_cases(self):
        """Test specific regression cases found in database."""
        # This was the original problematic case
        input_authors = ["Emily O&#x27;Leary", "Emily O'Leary"]

        # Test individual cleaning
        cleaned_1 = self.cleaner._clean_author_name(input_authors[0])
        cleaned_2 = self.cleaner._clean_author_name(input_authors[1])

        assert cleaned_1 == "Emily O'Leary"
        assert cleaned_2 == "Emily O'Leary"

        # Test full byline cleaning with deduplication
        byline = ", ".join(input_authors)
        result = self.cleaner.clean_byline(byline)

        # Should be deduplicated to single clean name
        assert result == ["Emily O'Leary"]
        assert len(result) == 1  # Ensure deduplication worked

    def test_no_html_entities(self):
        """Test that normal names without HTML entities work correctly."""
        test_cases = [
            ("John Smith", "John Smith"),
            ("Mary Johnson", "Mary Johnson"),
            ("Dr. Robert Chen", "Dr. Robert Chen"),
        ]

        for input_name, expected in test_cases:
            result = self.cleaner._clean_author_name(input_name)
            assert result == expected, (
                f"Expected '{expected}', got '{result}' for input '{input_name}'"
            )

    def test_empty_and_none_inputs(self):
        """Test handling of empty and None inputs."""
        assert self.cleaner._clean_author_name("") == ""
        # Note: _clean_author_name expects str, so we only test empty string
        assert self.cleaner.clean_byline("") == []


if __name__ == "__main__":
    # Allow running the test file directly
    pytest.main([__file__, "-v"])
