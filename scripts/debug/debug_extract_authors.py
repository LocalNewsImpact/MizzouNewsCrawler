#!/usr/bin/env python3
"""Debug the _extract_authors method for mary johnson."""

import os
import sys

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.byline_cleaner import BylineCleaner


def debug_extract_authors():
    """Debug the _extract_authors method."""
    cleaner = BylineCleaner(enable_telemetry=False)

    # Test what _extract_authors does with 'mary johnson'
    text = 'mary johnson'
    print(f"Input to _extract_authors: '{text}'")

    authors = cleaner._extract_authors(text)
    print(f"Output from _extract_authors: {authors}")
    print(f"Type: {type(authors)}")

    # Test with original byline too
    byline = "By Mary Johnson Special to The Times"
    print(f"\nTesting with full byline: '{byline}'")
    authors2 = cleaner._extract_authors(byline)
    print(f"Output from _extract_authors: {authors2}")


if __name__ == "__main__":
    debug_extract_authors()
