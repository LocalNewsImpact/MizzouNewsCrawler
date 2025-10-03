#!/usr/bin/env python3

"""Test single names with punctuation (no spaces)."""

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_single_names_with_punctuation():
    """Test that names with punctuation but no spaces are treated as single names."""

    cleaner = BylineCleaner(enable_telemetry=False)

    test_cases = [
        # Single names with apostrophes
        ("O'Connor", ["O'Connor"]),
        ("D'Angelo", ["D'Angelo"]),
        ("McDonald's", ["McDonald's"]),  # Though this might be filtered as non-name
        # Single names with hyphens
        ("Jean-Luc", ["Jean-Luc"]),
        ("Mary-Jane", ["Mary-Jane"]),
        ("Al-Rashid", ["Al-Rashid"]),
        # Single names with both
        ("O'Brien-Smith", ["O'Brien-Smith"]),
        # Regular single names (should be preserved if valid)
        ("Madonna", ["Madonna"]),
        ("Cher", ["Cher"]),
        ("Prince", ["Prince"]),
        # Make sure we're not splitting on punctuation
        ("O'Connor, Staff Writer", ["O'Connor"]),  # Should extract just the name
    ]

    print("Testing single names with punctuation...")
    print("=" * 50)

    for i, (byline, expected) in enumerate(test_cases, 1):
        result = cleaner.clean_byline(byline)

        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"{i:2d}. '{byline}'")
        print(f"    Expected: {expected}")
        print(f"    Got:      {result}")
        print(f"    Status:   {status}")

        if result != expected:
            # Debug the issue
            part_type = cleaner._identify_part_type(byline)
            print(f"    Debug:    Part type = '{part_type}'")

        print()


if __name__ == "__main__":
    test_single_names_with_punctuation()
