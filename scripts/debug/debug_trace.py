#!/usr/bin/env python3

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def trace_part_type():
    """Trace through the part type identification."""
    cleaner = BylineCleaner()

    part = "ROBERT DAVIS III"
    print(f"Tracing: {part}")

    part = part.strip()
    if not part:
        print("→ empty")
        return

    # Check for email
    if '@' in part and '.' in part:
        print("→ email (has @ and .)")
        return

    # Check for titles/journalism words
    part_words = part.lower().split()
    title_word_count = 0

    print(f"Words: {part_words}")

    # Check for non-name contexts with Roman numerals
    if (len(part_words) == 2 and
            part_words[0] in ['chapter', 'section', 'volume', 'part',
                              'book', 'act', 'scene'] and
            part_words[1] in ['ii', 'iii', 'iv', 'v', 'vi', 'vii',
                              'viii', 'ix', 'x']):
        print("→ title (non-name Roman context)")
        return

    # Count title words
    for word in part_words:
        is_title_word = False

        if word in cleaner.TITLES_TO_REMOVE:
            is_title_word = True
            print(f"  '{word}' in TITLES_TO_REMOVE")
        elif word in cleaner.JOURNALISM_NOUNS:
            is_title_word = True
            print(f"  '{word}' in JOURNALISM_NOUNS")
        elif (word.endswith(('st', 'nd', 'rd', 'th')) and
              len(word) > 2 and word[:-2].isdigit()):
            is_title_word = True
            print(f"  '{word}' is ordinal")
        elif (word.endswith(('1st', '2nd', '3rd')) or
              (len(word) >= 3 and word[-3:] in ['1st', '2nd', '3rd']) or
              (len(word) >= 2 and word[-2:].isdigit())):
            is_title_word = True
            print(f"  '{word}' has number pattern")

        if is_title_word:
            title_word_count += 1

    print(f"Title word count: {title_word_count}")

    # Enhanced logic: check if this looks like a title phrase
    has_title_pattern = False
    for i, word in enumerate(part_words):
        word_lower = word.lower()
        if (word_lower in cleaner.TITLES_TO_REMOVE or
            word_lower in cleaner.JOURNALISM_NOUNS):
            has_title_pattern = True
            print(f"  Found title pattern with '{word}'")
            break

    print(f"Has title pattern: {has_title_pattern}")

    # If we have title patterns and numbers/ordinals, it's likely all title
    if has_title_pattern and title_word_count >= len(part_words) * 0.6:
        print("→ title (title pattern + enough title words)")
        return

    # If most words are titles/journalism terms, it's a title section
    if title_word_count >= len(part_words) / 2:
        print("→ title (majority title words)")
        return

    # If it has some title words but not majority, it's mixed
    if title_word_count > 0:
        print("→ mixed (some title words)")
        return

    # Check if it looks like a name
    name_conditions = [
        len(part_words) <= 3,
        all(word.replace('.', '').isalpha() for word in part_words),
        not any(word.lower() in cleaner.TITLES_TO_REMOVE or
               word.lower() in cleaner.JOURNALISM_NOUNS for word in part_words)
    ]

    print(f"Name conditions: {name_conditions}")

    if all(name_conditions):
        print("→ name (all conditions met)")
        return

    print("→ mixed (default)")


if __name__ == "__main__":
    trace_part_type()
