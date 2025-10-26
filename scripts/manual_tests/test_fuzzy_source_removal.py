#!/usr/bin/env python3
"""Test script to verify fuzzy matching for source name removal."""

import logging
from src.utils.byline_cleaner import BylineCleaner

# Set up logging to see the info messages
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def test_fuzzy_source_removal():
    """Test the fuzzy matching for source name removal."""
    print("Testing Fuzzy Source Name Removal")
    print("=" * 50)

    cleaner = BylineCleaner()

    # Test cases with different variations
    test_cases = [
        # (author_text, source_name, expected_behavior)
        (
            "Dan Wehmer Webster Citizen",
            "Webster County Citizen",
            "Should remove 'Webster Citizen'",
        ),
        (
            "Matthew McFarland Webster Citizen",
            "Webster County Citizen",
            "Should remove 'Webster Citizen'",
        ),
        ("John Smith", "Webster County Citizen", "Should keep 'John Smith'"),
        ("Webster Citizen", "Webster County Citizen", "Should remove entire string"),
        (
            "WEBSTER COUNTY CITIZEN",
            "Webster County Citizen",
            "Should remove (case insensitive)",
        ),
        (
            "webster citizen",
            "Webster County Citizen",
            "Should remove (case insensitive)",
        ),
        ("Jane Doe Daily Herald", "The Daily Herald", "Should remove 'Daily Herald'"),
        ("Bob Wilson Chronicle", "Springfield Chronicle", "Should remove 'Chronicle'"),
        ("Alice Brown Times", "Local Times", "Should remove 'Times'"),
        ("Mike Davis", "Webster County Citizen", "Should keep (no similarity)"),
        ("Sarah Wilson Webster", "Webster County Citizen", "Should remove 'Webster'"),
    ]

    print(f"Testing with {len(test_cases)} test cases:")
    print()

    for i, (author_text, source_name, expected) in enumerate(test_cases, 1):
        print(f"Test {i}: {expected}")
        print(f"  Input: '{author_text}' | Source: '{source_name}'")

        # Test the _remove_source_name method directly
        result = cleaner._remove_source_name(author_text, source_name)

        print(f"  Output: '{result}'")

        # Show if something was removed
        if result != author_text:
            if result == "":
                print("  ✅ Removed entire author field (likely publication name)")
            else:
                print(f"  ✅ Cleaned: '{author_text}' → '{result}'")
        else:
            print("  ➡️  No change (kept original)")

        print()

    print("=" * 50)
    print("Testing full byline cleaning with source names:")
    print()

    # Test the full clean_byline method with source names
    full_test_cases = [
        ("By Dan Wehmer Webster Citizen", "Webster County Citizen"),
        ("Matthew McFarland, Webster Citizen Staff Writer", "Webster County Citizen"),
        ("JANE DOE | DAILY HERALD", "The Daily Herald"),
        ("Staff Report - Chronicle News", "Springfield Chronicle"),
    ]

    for raw_byline, source_name in full_test_cases:
        print("Full cleaning test:")
        print(f"  Raw byline: '{raw_byline}'")
        print(f"  Source: '{source_name}'")

        # Test full cleaning process
        result = cleaner.clean_byline(raw_byline, source_name=source_name)

        print(f"  Cleaned result: {result}")
        print()


if __name__ == "__main__":
    test_fuzzy_source_removal()
