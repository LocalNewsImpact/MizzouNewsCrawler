#!/usr/bin/env python3
"""
Test the byline cleaner with names containing apostrophes.
"""

from src.utils.byline_cleaner import BylineCleaner


def test_apostrophe_names():
    """Test various names with apostrophes."""
    cleaner = BylineCleaner()

    test_cases = [
        "Sean O'Connor",
        "Mary O'Brien",
        "Patrick O'Reilly",
        "D'Angelo Russell",
        "Jean-Luc D'Artagnan",
        "Michael O'Sullivan",
        "Katie O'Malley",
        "By Sean O'Connor, Staff Reporter",
        "O'Connor, Sean",
        "SEAN O'CONNOR",
        "sean o'connor",
        "O'brien, Mary Jane",
    ]

    print("🧪 TESTING APOSTROPHE NAMES")
    print("=" * 60)

    for i, test_case in enumerate(test_cases, 1):
        print(f"{i:2d}. Input:  '{test_case}'")

        try:
            result = cleaner.clean_byline(test_case)
            print(f"    Output: {result}")

            # Check for common issues
            issues = []
            if result:
                for name in result:
                    # Check if empty
                    if not name.strip():
                        issues.append("empty result")
                    # Check if apostrophe was incorrectly processed
                    elif "'" in test_case and "'" not in name:
                        issues.append("apostrophe removed")
            else:
                issues.append("no result returned")

            if issues:
                print(f"    Issues: {', '.join(issues)}")
                print("    ❌ FAILED")
            else:
                print("    ✅ PASSED")

        except Exception as e:
            print(f"    ERROR: {e}")
            print("    ❌ FAILED")

        print()

    # Test individual method components
    print("\n🔍 TESTING INDIVIDUAL COMPONENTS")
    print("=" * 60)

    test_name = "Sean O'Connor"
    print(f"Testing with: '{test_name}'")

    # Test basic cleaning
    basic_cleaned = cleaner._basic_cleaning(test_name)
    print(f"1. Basic cleaning: '{basic_cleaned}'")

    # Test individual name cleaning
    name_cleaned = cleaner._clean_author_name(test_name)
    print(f"2. Name cleaning: '{name_cleaned}'")

    # Test capitalization normalization
    cap_normalized = cleaner._normalize_capitalization(test_name)
    print(f"3. Capitalization: '{cap_normalized}'")

    # Test with different cases
    cases = ["SEAN O'CONNOR", "sean o'connor", "Sean o'connor", "sEAN O'cONNOR"]

    for case in cases:
        normalized = cleaner._normalize_capitalization(case)
        print(f"   '{case}' -> '{normalized}'")


if __name__ == "__main__":
    test_apostrophe_names()
