#!/usr/bin/env python3
"""
Test the type identification logic specifically.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from src.utils.byline_cleaner import BylineCleaner


def test_type_identification():
    """Test the _identify_part_type method."""

    cleaner = BylineCleaner()

    test_cases = [
        # Names
        ("Jane Doe", "name"),
        ("John Smith", "name"),
        ("Mary Johnson", "name"),
        ("Bob Wilson", "name"),
        # Emails
        ("jane.doe@news.com", "email"),
        ("john@email.com", "email"),
        ("reporter@newspaper.org", "email"),
        # Titles
        ("Senior Political Editor", "title"),
        ("Staff Reporter", "title"),
        ("Managing Director", "title"),
        ("News Editor", "title"),
        ("Sports Editor", "title"),
        ("Copy Editor", "title"),
        ("Editor", "title"),
        ("Reporter", "title"),
        ("Publisher", "title"),
        # Mixed (names with titles)
        ("Jane Smith Reporter", "mixed"),
        ("John Editor", "mixed"),
        # Edge cases
        ("", "empty"),
        ("   ", "empty"),
    ]

    print("Testing Type Identification Logic")
    print("=" * 50)

    all_passed = True

    for test_input, expected_type in test_cases:
        actual_type = cleaner._identify_part_type(test_input)

        if actual_type == expected_type:
            print(f"✓ '{test_input}' → {actual_type}")
        else:
            print(f"✗ '{test_input}' → {actual_type} (expected: {expected_type})")
            all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("All type identification tests PASSED! ✓")
    else:
        print("Some type identification tests FAILED ✗")

    return all_passed


def test_complex_cases():
    """Test complex comma-separated cases to show the full workflow."""

    cleaner = BylineCleaner()

    complex_cases = [
        "JANE DOE, JANE.DOE@NEWS.COM, Senior Political Editor",
        "JOHN SMITH, JOHN@EMAIL.COM, Staff Reporter",
        "Mary Johnson, Sports Editor, News Writer",
        "Bob Wilson, Editor, Publisher, Managing Director",
    ]

    print("\nTesting Complex Cases - Full Workflow")
    print("=" * 50)

    for case in complex_cases:
        print(f"\nCase: '{case}'")

        # Show type identification for each part
        parts = case.split(",")
        for i, part in enumerate(parts):
            part_type = cleaner._identify_part_type(part)
            print(f"  Part {i + 1}: '{part.strip()}' → {part_type}")

        # Show final result
        result = cleaner.clean_byline(case)
        print(f"  Final result: '{result}'")


if __name__ == "__main__":
    test_type_identification()
    test_complex_cases()
