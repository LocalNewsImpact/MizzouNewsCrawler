#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from utils.byline_cleaner import BylineCleaner


def test_manual():
    """Test with manually typed string."""
    cleaner = BylineCleaner()

    # Type it manually
    test = "ROBERT DAVIS III"

    # Check character by character
    print(f"String: '{test}'")
    print(f"Length: {len(test)}")
    print(f"Repr: {repr(test)}")

    result = cleaner._identify_part_type(test)
    print(f"Result: {result}")

    # Test each condition manually
    part_words = test.lower().split()
    print(f"Words: {part_words}")

    # Check if iii is somehow in the sets
    if "iii" in cleaner.TITLES_TO_REMOVE:
        print("'iii' IS in TITLES_TO_REMOVE")
    else:
        print("'iii' is NOT in TITLES_TO_REMOVE")

    if "iii" in cleaner.JOURNALISM_NOUNS:
        print("'iii' IS in JOURNALISM_NOUNS")
    else:
        print("'iii' is NOT in JOURNALISM_NOUNS")


if __name__ == "__main__":
    test_manual()
