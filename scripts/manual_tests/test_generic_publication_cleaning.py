#!/usr/bin/env python3
"""
Test that generic publication terms are now properly cleaned instead of preserved.
"""

from src.utils.byline_cleaner import BylineCleaner


def test_generic_publication_cleaning():
    """Test that generic publication terms are cleaned, not preserved."""
    cleaner = BylineCleaner()

    # These should now be cleaned as regular bylines, not preserved as wire services
    generic_publication_tests = [
        ("John Smith, Tribune Reporter", "John Smith"),
        ("Mary Johnson, News Editor", "Mary Johnson"),
        ("Bob Wilson, Herald Staff", "Bob Wilson"),
        ("Sarah Davis, Gazette Writer", "Sarah Davis"),
        ("Mike Brown, Times Correspondent", "Mike Brown"),
        ("Lisa Chen, Post Reporter", "Lisa Chen"),
        ("Tom Garcia, Journal Editor", "Tom Garcia"),
        ("Daily News Staff", ""),  # Should be cleaned to empty since it's all titles
        ("Weekly Tribune", ""),  # Should be cleaned to empty since it's all titles
    ]

    print("Testing Generic Publication Term Cleaning:")
    print("=" * 60)

    all_passed = True
    for input_byline, expected in generic_publication_tests:
        result = cleaner.clean_byline(input_byline)

        if result == expected:
            print(f"✓ '{input_byline}' → '{result}'")
        else:
            print(f"✗ '{input_byline}' → '{result}' (expected: '{expected}')")
            all_passed = False

    print("\n" + "=" * 60)

    # Also test that strong wire services are still preserved
    print("\nConfirming Strong Wire Services Still Preserved:")
    print("=" * 60)

    strong_wire_tests = [
        ("Associated Press", "Associated Press"),
        ("Reuters", "Reuters"),
        ("CNN", "CNN"),
        ("Bloomberg News", "Bloomberg News"),
    ]

    for input_byline, expected in strong_wire_tests:
        result = cleaner.clean_byline(input_byline)

        if result == expected:
            print(f"✓ '{input_byline}' → '{result}' (preserved)")
        else:
            print(f"✗ '{input_byline}' → '{result}' (expected: '{expected}')")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("All generic publication cleaning tests PASSED! ✓")
        print("Wire service detection is now properly specific.")
    else:
        print("Some tests FAILED! ✗")

    return all_passed


if __name__ == "__main__":
    test_generic_publication_cleaning()
