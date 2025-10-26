#!/usr/bin/env python3
"""
Test the improved tuple logic for byline cleaning.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from src.utils.byline_cleaner import BylineCleaner


def test_tuple_logic():
    """Test the improved logic for handling comma-separated tuples."""

    cleaner = BylineCleaner()

    # Test cases that should demonstrate the improved tuple logic
    test_cases = [
        # Complex cases with emails and multiple titles - should extract just the name
        ("JANE DOE, JANE.DOE@NEWS.COM, Senior Political Editor", ["Jane Doe"]),
        ("JOHN SMITH, JOHN@EMAIL.COM, Staff Reporter", ["John Smith"]),
        # Multiple titles - should keep only first part (the name)
        ("Mary Johnson, Sports Editor, News Writer", ["Mary Johnson"]),
        ("Bob Wilson, Editor, Publisher, Managing Director", ["Bob Wilson"]),
        # "And" separated authors should be preserved as separate array elements
        ("Sarah Davis and Tom Brown, Reporters", ["Sarah Davis", "Tom Brown"]),
        ("Mike Chen, Lisa Park", ["Mike Chen", "Lisa Park"]),  # Two names
        # Single name with one title (existing logic should work)
        ("Alex Thompson, Staff Writer", ["Alex Thompson"]),
        # Wire services should still be preserved
        ("Associated Press", ["Associated Press"]),
        # Multiple clear titles - should keep only first part
        ("Jennifer Lee, Staff Reporter, News Editor, Copy Editor", ["Jennifer Lee"]),
    ]

    print("Testing Improved Tuple Logic for Byline Cleaning")
    print("=" * 60)

    all_passed = True
    for input_byline, expected in test_cases:
        result = cleaner.clean_byline(input_byline)

        status = "✓" if result == expected else "✗"
        print(f"{status} '{input_byline}'")
        print(f"    Expected: '{expected}'")
        print(f"    Got:      '{result}'")

        if result != expected:
            all_passed = False

        print()

    print("=" * 60)
    if all_passed:
        print("All tuple logic tests PASSED! ✓")
    else:
        print("Some tests FAILED - tuple logic needs refinement ✗")

    return all_passed


if __name__ == "__main__":
    test_tuple_logic()
