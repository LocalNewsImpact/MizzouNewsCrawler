"""
Test byline cleaning storage format integration.

This test validates that the byline cleaner returns list format
and that it's properly converted to JSON for database storage.
"""

import json
import pytest

from src.utils.byline_cleaner import BylineCleaner


class TestBylineStorageFormat:
    """Test byline cleaning and storage format conversion."""

    def test_byline_cleaner_returns_list(self):
        """Test that byline cleaner returns a list of cleaned names."""
        cleaner = BylineCleaner()

        # Test with duplicate names and titles - should filter out photo credit
        raw_author = "Photos Jeremy Jacob, Sports Editor, Jeremy Jacob, Sports Editor"
        result = cleaner.clean_byline(raw_author)

        assert isinstance(result, list), "Byline cleaner should return a list"
        assert result == ["Jeremy Jacob"], (
            f"Expected cleaned list without photo credit, got {result}"
        )

    def test_json_conversion_for_database(self):
        """Test converting cleaned byline list to JSON for database storage."""
        cleaner = BylineCleaner()

        # Test various author formats
        test_cases = [
            ("Jeremy Jacob, Sports Editor", ["Jeremy Jacob"]),
            (
                "Photos Jeremy Jacob, Sports Editor, Jeremy Jacob, Sports Editor",
                ["Jeremy Jacob"],
            ),
            ("John Doe", ["John Doe"]),
            ("Jane Smith, Reporter, John Doe, Editor", ["Jane Smith", "John Doe"]),
            ("Photo by Jeremy Jacob", []),  # Photo credits should be filtered out
            ("Photos Jane Smith", []),  # Photo credits should be filtered out
        ]

        for raw_author, expected_list in test_cases:
            # Clean the byline
            cleaned_list = cleaner.clean_byline(raw_author)
            assert cleaned_list == expected_list, (
                f"Expected {expected_list}, got {cleaned_list}"
            )

            # Convert to JSON for database
            json_author = json.dumps(cleaned_list)
            assert isinstance(json_author, str), "JSON conversion should return string"

            # Test roundtrip to ensure data integrity
            restored_list = json.loads(json_author)
            assert restored_list == cleaned_list, (
                "Roundtrip conversion should preserve data"
            )

    def test_empty_and_none_author_handling(self):
        """Test handling of empty or None author values."""
        cleaner = BylineCleaner()

        # Test None
        result = cleaner.clean_byline(None)
        assert result == [], "None author should return empty list"

        # Test empty string
        result = cleaner.clean_byline("")
        assert result == [], "Empty string should return empty list"

        # Test whitespace only
        result = cleaner.clean_byline("   ")
        assert result == [], "Whitespace-only string should return empty list"

    def test_extraction_command_json_conversion(self):
        """Test that extraction command properly converts byline list to JSON."""
        # Simulate the extraction command logic without mocking
        raw_author = "Jeremy Jacob, Sports Editor, Jane Smith, Reporter"
        cleaner = BylineCleaner()
        cleaned_list = cleaner.clean_byline(raw_author)

        # This is what should happen in the extraction command
        cleaned_author = json.dumps(cleaned_list)

        # Verify the result
        expected_list = ["Jeremy Jacob", "Jane Smith"]
        assert cleaned_list == expected_list
        assert cleaned_author == '["Jeremy Jacob", "Jane Smith"]'
        assert isinstance(cleaned_author, str)

    def test_database_storage_format_examples(self):
        """Test realistic examples of what should be stored in database."""
        cleaner = BylineCleaner()

        examples = [
            {
                "raw": "Photos Jeremy Jacob, Sports Editor, Jeremy Jacob, Sports Editor",
                "expected_json": '["Jeremy Jacob"]',
            },
            {
                "raw": "Don Munsch, Editor, Don Munsch",
                "expected_json": '["Don Munsch"]',
            },
            {
                "raw": "Sky Strauss, Staff, Sky Strauss, Staff",
                "expected_json": '["Sky Strauss"]',
            },
            {"raw": "Photo by Jeremy Jacob", "expected_json": "[]"},
        ]

        for example in examples:
            cleaned_list = cleaner.clean_byline(example["raw"])
            json_result = json.dumps(cleaned_list)
            assert json_result == example["expected_json"], (
                f"For '{example['raw']}', expected '{example['expected_json']}', "
                f"got '{json_result}'"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
