#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_enhanced_title_recognition():
    """Test that titles with numbers and modifiers are properly recognized."""
    cleaner = BylineCleaner()

    test_cases = [
        # Titles with Roman numerals
        ("JOHN SMITH, Senior Editor II", ["John Smith"]),
        ("MARY JONES, Managing Director III", ["Mary Jones"]),
        ("BOB WILSON, Staff Writer IV", ["Bob Wilson"]),
        # Titles with regular numbers
        ("SARAH DAVIS, Reporter 1", ["Sarah Davis"]),
        ("MIKE CHEN, Editor 3", ["Mike Chen"]),
        ("LISA PARK, Photographer 2", ["Lisa Park"]),
        # Titles with ordinal numbers
        ("ALEX THOMPSON, 1st Assistant Editor", ["Alex Thompson"]),
        ("JENNIFER LEE, 2nd Copy Editor", ["Jennifer Lee"]),
        ("DAVID BROWN, 3rd Sports Reporter", ["David Brown"]),
        # Complex title combinations
        ("ROBERT DAVIS III, Senior Managing Editor II", ["Robert Davis III"]),
        ("WILLIAM JONES JR., Lead Sports Writer 1", ["William Jones Jr."]),
        # Multiple authors with numbered titles
        ("JOHN SMITH, Editor 1, MARY JONES, Reporter 2", ["John Smith", "Mary Jones"]),
        # Should NOT filter actual name suffixes
        ("ROBERT DAVIS III", ["Robert Davis III"]),  # This is a name, not a title
        ("JOHN SMITH II, Senior Editor", ["John Smith II"]),  # Name + title
        # Context-sensitive Roman numerals
        ("Chapter III, JOHN SMITH", ["John Smith"]),  # Chapter III should be filtered
        ("Volume II, MARY JONES", ["Mary Jones"]),  # Volume II should be filtered
        # Edge cases
        ("Senior Editor II, Managing Director III", []),  # All titles, no names
        ("JOHN SMITH and MARY JONES, Senior Editors", ["John Smith", "Mary Jones"]),
    ]

    print("Testing Enhanced Title Recognition")
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
        print("-" * 50)

    return all_passed


def test_part_type_identification():
    """Test the _identify_part_type method directly."""
    cleaner = BylineCleaner()

    test_cases = [
        # Should be recognized as titles
        ("Senior Editor II", "title"),
        ("Managing Director III", "title"),
        ("Staff Writer 1", "title"),
        ("2nd Assistant Editor", "title"),
        ("Chapter III", "title"),
        # Should be recognized as names
        ("John Smith", "name"),
        ("Robert Davis III", "name"),  # This is a person's name
        ("Mary Jones Jr.", "name"),
        # Should be mixed (name + title)
        ("John Smith, Editor", "mixed"),
        # Should be email
        ("john@news.com", "email"),
    ]

    print("\nTesting Part Type Identification")
    print("=" * 50)

    all_passed = True

    for input_text, expected in test_cases:
        result = cleaner._identify_part_type(input_text)
        print(f"Input: '{input_text}' → Expected: {expected}, Got: {result}")

        if result == expected:
            print("✅ PASS")
        else:
            print("❌ FAIL")
            all_passed = False
        print()

    return all_passed


if __name__ == "__main__":
    print("Testing Enhanced Title and Noun Recognition")
    print("=" * 60)

    title_tests_passed = test_enhanced_title_recognition()
    type_tests_passed = test_part_type_identification()

    if title_tests_passed and type_tests_passed:
        print("\n🎉 All enhanced recognition tests PASSED!")
        print("✅ Titles with numbers/modifiers properly filtered")
        print("✅ Name suffixes correctly preserved")
        print("✅ Context-sensitive recognition working")
    else:
        print("\n❌ Some tests failed - need more refinement")
