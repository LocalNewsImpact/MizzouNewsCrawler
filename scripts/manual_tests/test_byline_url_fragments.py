"""
Test URL fragment detection and cleaning in BylineCleaner.

This test suite verifies that the BylineCleaner correctly handles:
- Extraction of valid names from mixed content with URL fragments
- Filtering of continuous URL strings
- Proper handling of various separators (•, |, –, -, comma)
- Preservation of clean names without modification
"""

import pytest
from src.utils.byline_cleaner import BylineCleaner


class TestBylineURLFragments:
    """Test URL fragment detection and cleaning functionality."""

    @pytest.fixture
    def cleaner(self):
        """Create BylineCleaner instance with telemetry disabled."""
        return BylineCleaner(enable_telemetry=False)

    def test_url_fragment_detection(self, cleaner):
        """Test _is_url_fragment method for continuous URL detection."""
        # These should be detected as URL fragments (continuous strings)
        url_cases = [
            "website.com",
            "www.example.org",
            "http://site.net",
            "https://example.edu",
            "subdomain.site.gov",
            "Www..Com",  # Malformed but continuous
            "site.co.uk",
            "example.io",
        ]

        for url in url_cases:
            assert cleaner._is_url_fragment(url), (
                f"'{url}' should be detected as URL fragment"
            )

        # These should NOT be detected as URL fragments (spaced or non-URL)
        non_url_cases = [
            "Jack Silberberg • .Com",  # Spaced fragment
            "John Smith | . Org",  # Spaced fragment
            ". Com",  # Just spaced fragment
            "• .Org",  # Spaced with bullet
            "Jack Silberberg",  # Regular name
            "Dr. Robert Smith",  # Name with title
            "Mary Johnson-Wilson",  # Hyphenated name
            "Sarah O'Connor",  # Name with apostrophe
        ]

        for text in non_url_cases:
            assert not cleaner._is_url_fragment(text), (
                f"'{text}' should NOT be detected as URL fragment"
            )

    def test_name_extraction_from_mixed_content(self, cleaner):
        """Test extraction of valid names from mixed URL fragment content."""
        test_cases = [
            # (input, expected_output)
            ("Jack Silberberg • .Com", "Jack Silberberg"),
            ("John Smith | . Org", "John Smith"),
            ("Mary Johnson – .Net", "Mary Johnson"),
            ("Mike Davis, .Com", "Mike Davis"),
            ("Sarah Wilson - Website .Com", "Sarah Wilson"),  # No 'Website'
            ("Dr. Robert Chen • .Edu", "Dr. Robert Chen"),
            ("Lisa Park | Www.Site.Com", "Lisa Park"),
            ("Jennifer Adams — .Org", "Jennifer Adams"),
            ("Tom Wilson, .Net", "Tom Wilson"),
        ]

        for input_text, expected in test_cases:
            result = cleaner._clean_author_name(input_text)
            assert result == expected, (
                f"Input: '{input_text}' → Expected: '{expected}', Got: '{result}'"
            )

    def test_url_fragment_filtering(self, cleaner):
        """Test that pure URL fragments and invalid content are filtered."""
        filter_cases = [
            ". Com",  # Just spaced fragment
            "• .Org",  # Just spaced fragment with bullet
            "website.com",  # Continuous URL
            "www.example.org",  # Continuous URL with www
            "http://site.net",  # Full URL
            "Www..Com",  # Malformed continuous URL
            "",  # Empty string
            "   ",  # Just spaces
        ]

        for input_text in filter_cases:
            result = cleaner._clean_author_name(input_text)
            assert result == "", f"'{input_text}' should be filtered out (empty result)"

    def test_clean_names_passthrough(self, cleaner):
        """Test that clean names pass through unchanged."""
        clean_cases = [
            "Jack Silberberg",
            "Mary Johnson",
            "Dr. Robert Smith",
            "Jennifer Adams-Wilson",
            "Sarah O'Connor",
            "Michael Chen Jr.",
            "Prof. Elizabeth Davis",
        ]

        for name in clean_cases:
            result = cleaner._clean_author_name(name)
            assert result == name, (
                f"Clean name '{name}' should pass through unchanged, got '{result}'"
            )

    def test_separator_variations(self, cleaner):
        """Test handling of different separator types."""
        separator_cases = [
            # (input, expected_name)
            ("John Doe • .Com", "John Doe"),  # Bullet
            ("Jane Smith | .Org", "Jane Smith"),  # Pipe
            ("Bob Wilson – .Net", "Bob Wilson"),  # En-dash
            ("Alice Brown — .Edu", "Alice Brown"),  # Em-dash
            ("Tom Davis - .Gov", "Tom Davis"),  # Hyphen
            ("Sue Johnson, .Com", "Sue Johnson"),  # Comma
        ]

        for input_text, expected in separator_cases:
            result = cleaner._clean_author_name(input_text)
            assert result == expected, (
                f"Input: '{input_text}' → Expected: '{expected}', Got: '{result}'"
            )

    def test_complex_mixed_cases(self, cleaner):
        """Test complex cases with multiple elements."""
        complex_cases = [
            # (input, expected)
            ("Dr. James Wilson • Website .Com", "Dr. James Wilson"),
            ("Mary Jane Smith | Blog .Org", "Mary Jane Smith"),
            ("Prof. Robert Chen – News .Net", "Prof. Robert Chen"),
            ("Elizabeth Davis-Brown • Site .Edu", "Elizabeth Davis-Brown"),
        ]

        for input_text, expected in complex_cases:
            result = cleaner._clean_author_name(input_text)
            assert result == expected, (
                f"Complex case: '{input_text}' → Expected: '{expected}', "
                f"Got: '{result}'"
            )

    def test_edge_cases(self, cleaner):
        """Test edge cases and potential problem scenarios."""
        edge_cases = [
            # (input, expected)
            ("A B • .Com", "A B"),  # Short names
            ("John • Website • .Com", "John"),  # Multiple separators
            ("Dr. • .Com", ""),  # Title only (filtered)
            ("Website .Com", ""),  # No valid name
            ("John  •  .Com", "John"),  # Extra spaces
        ]

        for input_text, expected in edge_cases:
            result = cleaner._clean_author_name(input_text)
            assert result == expected, (
                f"Edge case: '{input_text}' → Expected: '{expected}', Got: '{result}'"
            )

    def test_full_byline_cleaning_with_url_fragments(self, cleaner):
        """Test full byline cleaning pipeline with URL fragment cases."""
        full_cleaning_cases = [
            # (input_byline, expected_authors)
            ("By Jack Silberberg • .Com", ["Jack Silberberg"]),
            ("John Smith | . Org", ["John Smith"]),
            ("Story by Mary Johnson – .Net", ["Mary Johnson"]),
            ("Dr. Robert Chen • .Edu and Lisa Park", ["Dr. Robert Chen", "Lisa Park"]),
            ("website.com", []),  # Pure URL should be filtered
            ("Jack Silberberg and Jane Doe • .Com", ["Jack Silberberg", "Jane Doe"]),
        ]

        for byline, expected_authors in full_cleaning_cases:
            result = cleaner.clean_byline(byline)
            assert result == expected_authors, (
                f"Byline: '{byline}' → Expected: {expected_authors}, Got: {result}"
            )

    def test_regression_cases(self, cleaner):
        """Test specific regression cases found in real data."""
        # These are based on actual problematic cases found in the database
        regression_cases = [
            ("Ivan Foley, Www..Com", "Ivan Foley"),
            ("Jack Silberberg • .Com", "Jack Silberberg"),
            ("Reporter Name | Website.Com", "Reporter Name"),
        ]

        for input_text, expected in regression_cases:
            result = cleaner._clean_author_name(input_text)
            assert result == expected, (
                f"Regression case: '{input_text}' → Expected: "
                f"'{expected}', Got: '{result}'"
            )


if __name__ == "__main__":
    # Allow running the test file directly
    pytest.main([__file__, "-v"])
