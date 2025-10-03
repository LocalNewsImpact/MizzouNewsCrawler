#!/usr/bin/env python3
"""Test duplicate removal."""

import sys
import os

sys.path.insert(0, os.path.abspath("."))

from src.utils.byline_cleaner import BylineCleaner


def test_duplicate_removal():
    """Test that final deduplication works."""
    print("Testing Final Duplicate Removal")
    print("=" * 40)

    cleaner = BylineCleaner()

    # Test cases that might create duplicates
    test_cases = [
        "Kelly Bowen, Kelly Bowen",
        "William Carroll and William Carroll",
        "Kelly Bowen, Staff Writer, Kelly Bowen",
        "John Smith, John Smith, Reporter",
        "Sarah Johnson",  # Normal case - no duplicates
    ]

    for byline in test_cases:
        print(f"\nByline: '{byline}'")
        result = cleaner.clean_byline(byline)
        print(f"Result: {result}")

        # Check for duplicates
        if isinstance(result, list):
            unique_count = len(set(author.lower() for author in result if author))
            total_count = len([author for author in result if author])
            if unique_count != total_count:
                print("❌ DUPLICATES STILL PRESENT!")
            else:
                print("✅ No duplicates")
        print("-" * 30)


if __name__ == "__main__":
    test_duplicate_removal()
