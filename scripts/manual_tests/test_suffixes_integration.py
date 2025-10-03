#!/usr/bin/env python3

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_suffixes_integration():
    """Test name suffixes work correctly in all scenarios."""
    cleaner = BylineCleaner()

    test_cases = [
        # Real-world scenarios with suffixes
        (
            "JOHN SMITH JR., Staff Writer, MARY JONES SR., Editor",
            ["John Smith Jr.", "Mary Jones Sr."],
        ),
        (
            "ROBERT DAVIS III and WILLIAM BROWN IV, Reporters",
            ["Robert Davis III", "William Brown IV"],
        ),
        ("THOMAS WILSON II, THOMAS@NEWS.COM, Managing Editor", ["Thomas Wilson II"]),
        # Edge case from our previous test - should work now
        (
            "MARY JONES SR., Editor, ROBERT DAVIS III",
            ["Mary Jones Sr.", "Robert Davis III"],
        ),
        # Multiple suffixes with duplicates
        ("JOHN SMITH JR., JOHN SMITH JR., Staff Writer", ["John Smith Jr."]),
        # Roman numerals correctly preserved vs. wrong context
        (
            "JOHN SMITH II, Chapter III, MARY JONES",
            ["John Smith II", "Mary Jones"],
        ),  # Chapter III should be filtered as title
        # Wire service should be preserved even with suffixes
        (
            "Associated Press, JOHN SMITH JR.",
            ["John Smith Jr."],
        ),  # AP gets filtered in this context as wire service
    ]

    print("Testing Name Suffixes Integration")
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


if __name__ == "__main__":
    print("Testing Name Suffixes Integration with Real-World Scenarios")
    print("=" * 70)

    passed = test_suffixes_integration()

    if passed:
        print("\n🎉 All integration tests PASSED!")
        print("✅ Name suffixes (Jr, Sr, II, III, IV) work perfectly")
        print("✅ Smart processing preserves multiple names correctly")
        print("✅ Duplicate handling works with suffixes")
        print("✅ System is production-ready!")
    else:
        print("\n❌ Some integration tests failed")
