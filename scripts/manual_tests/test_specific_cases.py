#!/usr/bin/env python3
"""Test the specific cases that are failing in extraction."""

import sys
import os

sys.path.insert(0, os.path.abspath("."))

from src.utils.byline_cleaner import BylineCleaner


def test_webster_cases():
    """Test the specific Webster County Citizen cases that are failing."""
    print("Testing Specific Webster County Citizen Cases")
    print("=" * 50)

    cleaner = BylineCleaner()

    # These are the actual cases from the extraction that returned empty
    test_cases = [
        (
            "Matthew McFarland Webster County Citizen 25k135@gmail.com",
            "Webster County Citizen",
        ),
        (
            "Dan Wehmer Webster County Citizen citizen@webstercountycitizen.com",
            "Webster County Citizen",
        ),
    ]

    for byline, source in test_cases:
        print(f"\nTesting byline: '{byline}'")
        print(f"Source: '{source}'")

        # Test the _remove_source_name function directly
        result = cleaner._remove_source_name(byline, source)
        print(f"_remove_source_name result: '{result}'")

        # Test the full clean_byline function
        full_result = cleaner.clean_byline(byline, source_name=source)
        print(f"clean_byline result: {full_result}")

        print("-" * 40)


if __name__ == "__main__":
    test_webster_cases()
