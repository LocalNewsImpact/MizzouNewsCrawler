#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_john_deatherage():
    """Test the John Deatherage case specifically."""
    cleaner = BylineCleaner()

    # This was the original input from the cleaning script output
    original = "John Deatherage, Quill Sports Contributor, John Deatherage, Quill Sports Contributor"

    print(f"Testing: {original}")
    result = cleaner.clean_byline(original)
    print(f"Result: {result}")

    # Test what we expect
    expected = ["John Deatherage"]
    print(f"Expected: {expected}")
    print(f"Match: {result == expected}")

    # Let's also test the current problematic output
    current_bad = "John Deatherage, John Deatherage"
    print(f"\nTesting current bad output: {current_bad}")
    result2 = cleaner.clean_byline(current_bad)
    print(f"Result: {result2}")


if __name__ == "__main__":
    test_john_deatherage()
