#!/usr/bin/env python3
"""
Debug the tuple logic to understand why email cases aren't being handled.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from src.utils.byline_cleaner import BylineCleaner


def debug_tuple_analysis():
    """Debug the tuple analysis for email cases."""

    cleaner = BylineCleaner()

    # Debug the problematic cases
    debug_cases = [
        "JANE DOE, JANE.DOE@NEWS.COM, Senior Political Editor",
        "JOHN SMITH, JOHN@EMAIL.COM, Staff Reporter",
    ]

    print("Debugging Tuple Analysis")
    print("=" * 50)

    for case in debug_cases:
        print(f"\nDebugging: '{case}'")

        # Manually replicate the logic from _extract_authors
        comma_parts = case.split(",")
        print(f"Comma parts: {comma_parts}")

        title_count = 0
        non_title_count = 0

        for i, part in enumerate(comma_parts):
            part = part.strip()
            if not part:
                continue

            part_words = part.lower().split()
            has_title_word = False
            has_email = "@" in part

            print(f"  Part {i}: '{part}' (words: {part_words})")
            print(f"    Has email: {has_email}")

            # Check if this part contains title/journalism words
            for word in part_words:
                if (
                    word in cleaner.TITLES_TO_REMOVE
                    or word in cleaner.JOURNALISM_NOUNS
                    or
                    # Check for plural forms
                    (word.endswith("s") and word[:-1] in cleaner.TITLES_TO_REMOVE)
                    or (word.endswith("s") and word[:-1] in cleaner.JOURNALISM_NOUNS)
                ):
                    has_title_word = True
                    print(f"    Found title/journalism word: '{word}'")
                    break

            if has_title_word or has_email:
                title_count += 1
                print(
                    f"    Classified as TITLE (title_word={has_title_word}, email={has_email})"
                )
            else:
                non_title_count += 1
                print("    Classified as NON-TITLE")

        print(
            f"  Summary: title_count={title_count}, non_title_count={non_title_count}, total_parts={len(comma_parts)}"
        )

        # Check the smart processing condition
        condition1 = title_count >= 2 and len(comma_parts) >= 3
        condition2 = title_count > non_title_count and len(comma_parts) >= 3
        smart_processing = condition1 or condition2

        print(f"  Smart processing condition: {smart_processing}")
        print(f"    Condition 1 (title_count >= 2 and len >= 3): {condition1}")
        print(
            f"    Condition 2 (title_count > non_title_count and len >= 3): {condition2}"
        )

        # Test actual cleaning
        result = cleaner.clean_byline(case)
        print(f"  Actual result: '{result}'")


if __name__ == "__main__":
    debug_tuple_analysis()
