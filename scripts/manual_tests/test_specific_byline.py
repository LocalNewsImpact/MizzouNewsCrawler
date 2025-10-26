#!/usr/bin/env python3

from src.utils.byline_cleaner import BylineCleaner


def test_specific_case():
    cleaner = BylineCleaner()

    # Test the specific case mentioned by the user
    test_byline = "Sarah Johnson and Mike Wilson, News Editors"

    print(f"Original: {test_byline}")

    # Test string output
    cleaned_string = cleaner.clean_byline(test_byline, return_json=False)
    print(f"String:   {cleaned_string}")

    # Test JSON output
    cleaned_json = cleaner.clean_byline(test_byline, return_json=True)
    print(f"JSON:     {cleaned_json}")

    print("\n" + "=" * 50)

    # Test a few more edge cases
    test_cases = [
        "John Smith, Editor",
        "Jane Doe and Bob Smith, Reporters",
        "Alice Brown, Staff Writer and Tom Green, News Editor",
        "Mark Davis, twitter: @markd, News Reporter",
    ]

    for test_case in test_cases:
        print(f"\nOriginal: {test_case}")
        result = cleaner.clean_byline(test_case, return_json=True)
        print(f"Result:   {result}")


if __name__ == "__main__":
    test_specific_case()
