#!/usr/bin/env python3
"""
Debug author extraction for simple names.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.utils.byline_cleaner import BylineCleaner


def debug_author_extraction():
    """Debug author extraction."""

    print("=== Debug Author Extraction ===\n")

    cleaner = BylineCleaner(enable_telemetry=False)

    test_cases = [
        "tom reporter",
        "Tom Reporter",
        "John Smith",
        "jane doe"
    ]

    for test_text in test_cases:
        print(f"Testing: '{test_text}'")
        authors = cleaner._extract_authors(test_text)
        print(f"   Extracted: {authors}")
        print()

if __name__ == "__main__":
    debug_author_extraction()
