"""
Test photo credit filtering in byline cleaning.
"""

import pytest
from src.utils.byline_cleaner import BylineCleaner


class TestPhotoCreditsFiltering:
    """Test that photo credits are properly filtered out of author bylines."""

    def test_photo_credit_identification(self):
        """Test that various photo credit formats are identified correctly."""
        cleaner = BylineCleaner()

        photo_credit_cases = [
            "Photos Jeremy Jacob",
            "Photo Jeremy Jacob",
            "Photos by Jeremy Jacob",
            "Photo by Jeremy Jacob",
            "PHOTOS John Doe",
            "PHOTO BY Jane Smith",
        ]

        for case in photo_credit_cases:
            part_type = cleaner._identify_part_type(case)
            assert part_type == "photo_credit", (
                f"'{case}' should be identified as photo_credit, got {part_type}"
            )

    def test_photo_credits_filtered_from_bylines(self):
        """Test that photo credits are filtered out of final results."""
        cleaner = BylineCleaner()

        test_cases = [
            # Case 1: Photo credit with author and title
            {
                "input": "Photos Jeremy Jacob, Sports Editor, Jeremy Jacob, Sports Editor",
                "expected": ["Jeremy Jacob"],
                "description": "Photo credit should be removed, author preserved",
            },
            # Case 2: Just a photo credit
            {
                "input": "Photos Jeremy Jacob",
                "expected": [],
                "description": "Pure photo credit should return empty list",
            },
            # Case 3: Photo by format
            {
                "input": "Photo by Jeremy Jacob",
                "expected": [],
                "description": "Photo by format should return empty list",
            },
            # Case 4: Multiple authors with photo credit
            {
                "input": "Photos Jane Smith, Jeremy Jacob, Sports Editor, Jane Smith, Reporter",
                "expected": ["Jeremy Jacob", "Jane Smith"],
                "description": "Photo credit removed, multiple authors preserved",
            },
            # Case 5: Normal author without photo credit
            {
                "input": "Jeremy Jacob, Sports Editor",
                "expected": ["Jeremy Jacob"],
                "description": "Normal author should be preserved",
            },
        ]

        for case in test_cases:
            result = cleaner.clean_byline(case["input"])
            assert result == case["expected"], (
                f"Test case: {case['description']}\n"
                f"Input: '{case['input']}'\n"
                f"Expected: {case['expected']}\n"
                f"Got: {result}"
            )

    def test_photo_vs_photographer_distinction(self):
        """Test that we distinguish between photo credits and photographer titles."""
        cleaner = BylineCleaner()

        # These should be filtered as photo credits
        photo_credits = ["Photos Jeremy Jacob", "Photo by Jeremy Jacob"]

        # These should be treated as titles and the person's name preserved
        photographer_titles = [
            "Jeremy Jacob, Photographer",
            "Jane Smith, Staff Photographer",
        ]

        for credit in photo_credits:
            result = cleaner.clean_byline(credit)
            assert result == [], (
                f"Photo credit '{credit}' should be filtered out, got {result}"
            )

        for title_case in photographer_titles:
            result = cleaner.clean_byline(title_case)
            expected_name = title_case.split(",")[0].strip()
            assert expected_name in result, (
                f"Photographer name should be preserved from '{title_case}', got {result}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
