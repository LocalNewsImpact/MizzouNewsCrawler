#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def debug_title_check():
    """Debug the title removal check."""
    cleaner = BylineCleaner()

    test_words = ["robert", "davis", "iii"]

    print("Checking TITLES_TO_REMOVE:")
    for word in test_words:
        if word in cleaner.TITLES_TO_REMOVE:
            print(f"  '{word}' IS in TITLES_TO_REMOVE")
        else:
            print(f"  '{word}' is NOT in TITLES_TO_REMOVE")

    print("\nChecking JOURNALISM_NOUNS:")
    for word in test_words:
        if word in cleaner.JOURNALISM_NOUNS:
            print(f"  '{word}' IS in JOURNALISM_NOUNS")
        else:
            print(f"  '{word}' is NOT in JOURNALISM_NOUNS")

    # Test the actual check
    has_title_words = any(
        word.lower() in cleaner.TITLES_TO_REMOVE
        or word.lower() in cleaner.JOURNALISM_NOUNS
        for word in test_words
    )
    print(f"\nAny title words found: {has_title_words}")

    # Test other conditions
    print(f"Length <= 3: {len(test_words) <= 3}")
    print(f"All alpha: {all(word.replace('.', '').isalpha() for word in test_words)}")


if __name__ == "__main__":
    debug_title_check()
