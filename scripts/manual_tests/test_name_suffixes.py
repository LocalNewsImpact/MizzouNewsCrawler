#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_name_suffixes():
    """Test that name suffixes (Jr, Sr, II, III, IV) are preserved."""
    cleaner = BylineCleaner()

    test_cases = [
        # Single names with suffixes
        ("JOHN SMITH JR.", ["John Smith Jr."]),
        ("MARY JONES SR.", ["Mary Jones Sr."]),
        ("ROBERT DAVIS II", ["Robert Davis II"]),
        ("WILLIAM BROWN III", ["William Brown III"]),
        ("THOMAS WILSON IV", ["Thomas Wilson IV"]),
        # Mixed case variations
        ("John Smith Jr", ["John Smith Jr"]),
        ("MARY JONES sr", ["Mary Jones Sr"]),
        ("Robert Davis ii", ["Robert Davis II"]),
        ("William Brown iii", ["William Brown III"]),
        ("Thomas Wilson iv", ["Thomas Wilson IV"]),
        # With periods and without
        ("JOHN SMITH JR.", ["John Smith Jr."]),
        ("JOHN SMITH JR", ["John Smith Jr"]),
        # Multiple authors with suffixes
        ("JOHN SMITH JR. and MARY JONES SR.", ["John Smith Jr.", "Mary Jones Sr."]),
        # With titles mixed in
        ("JOHN SMITH JR., Staff Writer", ["John Smith Jr."]),
        (
            "MARY JONES SR., Editor, ROBERT DAVIS III",
            ["Mary Jones Sr.", "Robert Davis III"],
        ),
        # Complex cases
        (
            "JOHN O'SMITH JR., MARY-JANE JONES SR., BOB WILSON III",
            ["John O'Smith Jr.", "Mary-Jane Jones Sr.", "Bob Wilson III"],
        ),
    ]

    print("Testing Name Suffix Preservation")
    print("=" * 50)

    all_passed = True

    for input_text, expected in test_cases:
        result = cleaner.clean_byline(input_text)
        print(f"Input: {input_text}")
        print(f"Expected: {expected}")
        print(f"Got:      {result}")

        if result == expected:
            print("✅ PASS")
        else:
            print("❌ FAIL")
            all_passed = False
        print("-" * 40)

    return all_passed


def test_edge_cases_with_suffixes():
    """Test edge cases to make sure we don't break other functionality."""
    cleaner = BylineCleaner()

    print("\nTesting Edge Cases with Suffixes")
    print("=" * 50)

    test_cases = [
        # Make sure we still filter actual titles
        ("Staff Writer, Editor, Reporter", []),
        # Wire services still preserved
        ("Associated Press", ["Associated Press"]),
        # Mix of real suffixes and title words
        ("JOHN SMITH JR., Reporter, MARY JONES", ["John Smith Jr.", "Mary Jones"]),
        # Roman numerals in wrong context should still be handled carefully
        ("CHAPTER II, JOHN SMITH", ["John Smith"]),
    ]

    for input_text, expected in test_cases:
        result = cleaner.clean_byline(input_text)
        print(f"Input: {input_text}")
        print(f"Expected: {expected}")
        print(f"Got:      {result}")
        print("-" * 40)


if __name__ == "__main__":
    print("Testing Name Suffix Preservation (Jr, Sr, II, III, IV)")
    print("=" * 60)

    suffix_tests_passed = test_name_suffixes()
    test_edge_cases_with_suffixes()

    if suffix_tests_passed:
        print("\n🎉 All suffix preservation tests PASSED!")
        print("✅ Jr, Sr, II, III, IV are now properly preserved")
    else:
        print("\n❌ Some tests failed - need to investigate")
