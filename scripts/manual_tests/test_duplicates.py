#!/usr/bin/env python3

from src.utils.byline_cleaner import BylineCleaner


def test_duplicates():
    cleaner = BylineCleaner()

    # Test cases that should result in duplicates after cleaning
    test_cases = [
        "John Smith, Editor and John Smith, Staff Writer",
        "Jane Doe and Jane Doe, Reporter",
        "Bob Johnson, News Editor and Bob Johnson",
        "Alice Brown, Staff and Alice Brown, Writer",
        "Mike Wilson and Mike Wilson, Journalist",
    ]

    print("Testing duplicate name removal after title cleaning:")
    print("=" * 60)

    for test_case in test_cases:
        print(f"\nOriginal: {test_case}")
        result = cleaner.clean_byline(test_case, return_json=True)
        print(f"Result:   {result}")
        print(f"Authors:  {result.get('authors', [])}")


if __name__ == "__main__":
    test_duplicates()
