#!/usr/bin/env python3
"""Debug the Mary Johnson case specifically."""

import os
import sys

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.utils.byline_cleaner import BylineCleaner


def debug_mary_johnson():
    """Debug the Mary Johnson case."""
    cleaner = BylineCleaner(enable_telemetry=False)

    byline = "By Mary Johnson Special to The Times"
    print(f"Testing: {byline}")

    # Test the special contributor extraction directly
    special_result = cleaner._extract_special_contributor(byline)
    print(f"Special contributor extraction: '{special_result}'")

    # Test full cleaning
    result = cleaner.clean_byline(
        byline=byline, return_json=True, source_name="The Times"
    )

    print(f"Full cleaning result: {result}")


if __name__ == "__main__":
    debug_mary_johnson()
