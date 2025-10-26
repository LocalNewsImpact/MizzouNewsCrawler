#!/usr/bin/env python3

from src.utils.byline_cleaner import BylineCleaner


def debug_journalism_filtering():
    """Debug why journalism terms aren't being filtered."""

    cleaner = BylineCleaner()

    # Test if the terms are actually in the list
    test_terms = ["team", "department", "name"]

    print("Checking if terms are in JOURNALISM_NOUNS:")
    for term in test_terms:
        in_list = term in cleaner.JOURNALISM_NOUNS
        print(f"'{term}' in JOURNALISM_NOUNS: {in_list}")

    print(f"\nJOURNALISM_NOUNS contains {len(cleaner.JOURNALISM_NOUNS)} terms")
    print("Sample terms:", list(cleaner.JOURNALISM_NOUNS)[:10])


if __name__ == "__main__":
    debug_journalism_filtering()
