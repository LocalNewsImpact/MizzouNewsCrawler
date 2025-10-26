#!/usr/bin/env python3
"""Debug the special contributor flow with detailed logging."""

import os
import sys

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.utils.byline_cleaner import BylineCleaner


def debug_with_logging():
    """Debug with detailed logging."""
    cleaner = BylineCleaner(enable_telemetry=False)

    # Monkey patch to add debug logging
    original_clean = cleaner.clean_byline

    def debug_clean(*args, **kwargs):
        print("Starting clean_byline...")
        result = original_clean(*args, **kwargs)
        print(f"Final result: {result}")
        return result

    cleaner.clean_byline = debug_clean

    # Test the problematic case
    byline = "By Mary Johnson Special to The Times"
    source_name = "The Times"

    print(f"Testing: {byline}")
    result = cleaner.clean_byline(byline, source_name=source_name)
    print(f"Result: {result}")


if __name__ == "__main__":
    debug_with_logging()
