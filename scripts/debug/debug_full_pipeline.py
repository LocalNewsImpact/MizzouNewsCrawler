#!/usr/bin/env python3
"""Debug the full Mary Johnson pipeline step by step."""

import os
import sys

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.byline_cleaner import BylineCleaner


def debug_full_pipeline():
    """Debug the full pipeline for Mary Johnson case."""
    cleaner = BylineCleaner(enable_telemetry=False)

    byline = "By Mary Johnson Special to The Times"
    source_name = "The Times"

    print(f"Original byline: {byline}")
    print(f"Source name: {source_name}")

    # Step 1: Extract special contributor
    special_result = cleaner._extract_special_contributor(byline)
    print(f"1. Special extraction: '{special_result}'")

    if special_result:
        # Step 2: Process like in clean_byline
        authors = [special_result]  # Start with extracted name
        print(f"2. Initial authors array: {authors}")

        # Step 3: Clean author names
        cleaned_authors = []
        for author in authors:
            cleaned = cleaner._clean_author_name(author)
            if cleaned:
                cleaned_authors.append(cleaned)
        print(f"3. After cleaning: {cleaned_authors}")

        # Step 4: Validate authors
        validated_authors = cleaner._validate_authors(cleaned_authors)
        print(f"4. After validation: {validated_authors}")

    # Compare with full pipeline
    print("\n--- Full pipeline ---")
    full_result = cleaner.clean_byline(byline, source_name=source_name)
    print(f"Full result: {full_result}")


if __name__ == "__main__":
    debug_full_pipeline()
