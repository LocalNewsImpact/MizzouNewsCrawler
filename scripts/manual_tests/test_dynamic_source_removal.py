#!/usr/bin/env python3
"""Test dynamic source name removal from author fields."""

import logging
from src.utils.byline_cleaner import BylineCleaner

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_dynamic_source_removal():
    """Test the dynamic source name removal functionality."""
    print("Testing Dynamic Source Name Removal")
    print("=" * 45)

    cleaner = BylineCleaner()

    # Test cases simulating real scenarios
    test_cases = [
        {
            "byline": "Dan Wehmer Webster Citizen",
            "source_name": "Webster County Citizen",
            "expected_result": "Dan Wehmer",
        },
        {
            "byline": "Matthew McFarland Webster Citizen",
            "source_name": "Webster County Citizen",
            "expected_result": "Matthew McFarland",
        },
        {
            "byline": "John Smith, Staff Reporter",
            "source_name": "Webster County Citizen",
            "expected_result": "John Smith",
        },
        {
            "byline": "Webster County Citizen",
            "source_name": "Webster County Citizen",
            "expected_result": "",
        },
        {
            "byline": "WEBSTER CITIZEN",
            "source_name": "Webster County Citizen",
            "expected_result": "",
        },
        {
            "byline": "Sarah Johnson Tribune",
            "source_name": "Daily Tribune",
            "expected_result": "Sarah Johnson",
        },
        {
            "byline": "Mike Wilson",
            "source_name": "Webster County Citizen",
            "expected_result": "Mike Wilson",
        },
    ]

    print(f"\nTesting {len(test_cases)} cases:\n")

    for i, test_case in enumerate(test_cases, 1):
        byline = test_case["byline"]
        source_name = test_case["source_name"]
        expected = test_case["expected_result"]

        print(f"Test {i}:")
        print(f"  Byline: '{byline}'")
        print(f"  Source: '{source_name}'")
        print(f"  Expected: '{expected}'")

        # Test the cleaning with source name
        result = cleaner.clean_byline(byline, source_name=source_name)

        # Extract the actual author name from the result
        if isinstance(result, list):
            actual = result[0] if result else ""
        else:
            actual = str(result)

        print(f"  Actual: '{actual}'")

        # Check if result matches expectation
        if actual == expected:
            print("  ✅ PASS")
        else:
            print("  ❌ FAIL")
        print()

    print("=" * 45)
    print("Dynamic source removal test complete!")


if __name__ == "__main__":
    test_dynamic_source_removal()
