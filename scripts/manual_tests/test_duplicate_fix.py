#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_duplicate_fix():
    """Test the specific duplicate case that was problematic."""
    cleaner = BylineCleaner()

    # The problematic case
    test_case = "ISABELLA VOLMERT and OBED LAMY, ISABELLA VOLMERT, OBED LAMY"

    print(f"Testing: {test_case}")
    result = cleaner.clean_byline(test_case)
    print(f"Result: {result}")
    print("Expected: ['Isabella Volmert', 'Obed Lamy']")

    # Verify it's correct
    expected = ["Isabella Volmert", "Obed Lamy"]
    if result == expected:
        print("✅ FIXED: Duplicate handling works correctly!")
        return True
    else:
        print("❌ STILL BROKEN: Duplicates not handled properly")
        return False


def test_other_cases():
    """Test that we didn't break other functionality."""
    cleaner = BylineCleaner()

    test_cases = [
        ("JANE DOE, STAFF WRITER", ["Jane Doe"]),
        ("The Associated Press", ["The Associated Press"]),
        ("JOHN SMITH and MARY JONES", ["John Smith", "Mary Jones"]),
        ("REPORTER@EMAIL.COM, JOHN DOE, JOHN DOE", ["John Doe"]),
    ]

    print("\nTesting other cases:")
    all_passed = True

    for input_text, expected in test_cases:
        result = cleaner.clean_byline(input_text)
        print(f"Input: {input_text}")
        print(f"Result: {result}")
        print(f"Expected: {expected}")

        if result == expected:
            print("✅ PASS")
        else:
            print("❌ FAIL")
            all_passed = False
        print()

    return all_passed


if __name__ == "__main__":
    print("Testing duplicate fix...")

    duplicate_fixed = test_duplicate_fix()
    other_cases_work = test_other_cases()

    if duplicate_fixed and other_cases_work:
        print("🎉 All tests pass! Duplicate handling is fixed.")
    else:
        print("💥 Some tests failed. Need more work.")
