#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def debug_robert_davis():
    """Debug why 'ROBERT DAVIS III' is classified as mixed."""
    cleaner = BylineCleaner()

    test = "ROBERT DAVIS III"
    print(f"Debugging: {test}")

    part_type = cleaner._identify_part_type(test)
    print(f"Part type: {part_type}")

    # Check word analysis
    part_words = test.lower().split()
    print(f"Words: {part_words}")

    title_word_count = 0
    for word in part_words:
        is_title_word = False

        # Check against title lists
        if word in cleaner.TITLES_TO_REMOVE:
            print(f"  '{word}' is in TITLES_TO_REMOVE")
            is_title_word = True
        elif word in cleaner.JOURNALISM_NOUNS:
            print(f"  '{word}' is in JOURNALISM_NOUNS")
            is_title_word = True
        # Check for ordinals
        elif (word.endswith(('st', 'nd', 'rd', 'th')) and
              len(word) > 2 and word[:-2].isdigit()):
            print(f"  '{word}' is an ordinal")
            is_title_word = True
        elif (word.endswith(('1st', '2nd', '3rd')) or
              (len(word) >= 3 and word[-3:] in ['1st', '2nd', '3rd']) or
              (len(word) >= 2 and word[-2:].isdigit())):
            print(f"  '{word}' looks like number/ordinal")
            is_title_word = True

        if is_title_word:
            title_word_count += 1
            print(f"  → Title word count now: {title_word_count}")

    print(f"Total title words: {title_word_count} out of {len(part_words)}")


if __name__ == "__main__":
    debug_robert_davis()
