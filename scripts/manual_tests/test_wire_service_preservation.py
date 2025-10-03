#!/usr/bin/env python3
"""
Test wire service preservation functionality in byline cleaner.
"""

from src.utils.byline_cleaner import BylineCleaner


def test_wire_service_preservation():
    """Test that wire service bylines are preserved unchanged."""
    cleaner = BylineCleaner()

    # Test cases for wire service preservation
    wire_service_tests = [
        # Direct wire service names
        ("Associated Press", "Associated Press"),
        ("AP", "AP"),
        ("Reuters", "Reuters"),
        ("CNN", "CNN"),
        ("NPR", "NPR"),
        ("PBS", "PBS"),
        ("Bloomberg", "Bloomberg"),
        # With prefixes
        ("By Associated Press", "By Associated Press"),
        ("From Reuters", "From Reuters"),
        ("Source: AP", "Source: AP"),
        ("- CNN", "- CNN"),
        # With additional content
        ("Associated Press reporter", "Associated Press reporter"),
        ("Reuters News Service", "Reuters News Service"),
        # Full organization names
        ("The New York Times", "The New York Times"),
        ("The Washington Post", "The Washington Post"),
        ("USA Today", "USA Today"),
        ("Wall Street Journal", "Wall Street Journal"),
        ("Los Angeles Times", "Los Angeles Times"),
    ]

    print("Testing Wire Service Preservation:")
    print("=" * 50)

    all_passed = True
    for input_byline, expected in wire_service_tests:
        result = cleaner.clean_byline(input_byline)

        if result == expected:
            print(f"✓ '{input_byline}' → '{result}'")
        else:
            print(f"✗ '{input_byline}' → '{result}' (expected: '{expected}')")
            all_passed = False

    print("\n" + "=" * 50)

    # Test non-wire service bylines to ensure they're still cleaned
    print("\nTesting Non-Wire Service Cleaning (should still be processed):")
    print("=" * 50)

    non_wire_tests = [
        ("JOHN SMITH, Staff Reporter", "John Smith"),
        ("Jane Doe, Editor", "Jane Doe"),
        ("Bob Jones, Publisher", "Bob Jones"),
        ("MARY WILLIAMS and SARAH DAVIS", ["Mary Williams", "Sarah Davis"]),
        ("Tom Brown, Staff Writer, Tom Brown", "Tom Brown"),
    ]

    for input_byline, expected in non_wire_tests:
        result = cleaner.clean_byline(
            input_byline, return_json=isinstance(expected, list)
        )

        if result == expected:
            print(f"✓ '{input_byline}' → '{result}'")
        else:
            print(f"✗ '{input_byline}' → '{result}' (expected: '{expected}')")
            all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("All wire service preservation tests PASSED! ✓")
    else:
        print("Some tests FAILED! ✗")

    return all_passed


if __name__ == "__main__":
    test_wire_service_preservation()
