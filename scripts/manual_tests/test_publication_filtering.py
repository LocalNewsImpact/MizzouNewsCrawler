#!/usr/bin/env python3

"""Test that multi-word publication names are still filtered correctly."""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_publication_filtering():
    """Test that multi-word publication names are correctly filtered."""

    cleaner = BylineCleaner(enable_telemetry=False)

    # These should be filtered (multi-word publication names)
    should_filter = [
        "New York Times",
        "Washington Post",
        "Los Angeles Tribune",
        "Kansas City Star",
        "USA Today",
        "Wall Street Journal",
        "Chicago Tribune",
        "Boston Globe",
    ]

    # These should NOT be filtered (single names)
    should_not_filter = [
        "Prince",
        "Madonna",
        "Cher",
        "O'Connor",
        "McDonald's",
        "D'Angelo",
        "Jean-Luc",
    ]

    print("Testing publication name filtering...")
    print("=" * 50)

    print("Multi-word publication names (should be filtered):")
    for pub_name in should_filter:
        is_pub = cleaner._is_publication_name(pub_name)
        result = cleaner.clean_byline(pub_name)
        status = "✅ FILTERED" if len(result) == 0 else f"❌ NOT FILTERED: {result}"
        print(f"  '{pub_name}': {status} (is_publication_name: {is_pub})")

    print("\nSingle names (should NOT be filtered):")
    for name in should_not_filter:
        is_pub = cleaner._is_publication_name(name)
        result = cleaner.clean_byline(name)
        status = "✅ PRESERVED" if len(result) > 0 else "❌ INCORRECTLY FILTERED"
        print(f"  '{name}': {status} (is_publication_name: {is_pub})")


if __name__ == "__main__":
    test_publication_filtering()
