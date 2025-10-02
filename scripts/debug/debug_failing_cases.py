#!/usr/bin/env python3
"""
Debug the failing test cases.
"""

from src.utils.byline_cleaner import BylineCleaner


def debug_failing_cases():
    """Debug the specific failing cases."""
    cleaner = BylineCleaner()

    failing_cases = [
        "O'Connor, Sean, Staff Reporter",
        "Photos, John Smith",
        "D'Artagnan, Jean-Luc"
    ]

    print("🔍 DEBUGGING FAILING CASES")
    print("=" * 60)

    for case in failing_cases:
        print(f"\nDebugging: '{case}'")

        # Test part type identification for each comma-separated part
        parts = case.split(',')
        print(f"  Parts: {[p.strip() for p in parts]}")

        for i, part in enumerate(parts):
            part = part.strip()
            part_type = cleaner._identify_part_type(part)
            print(f"    Part {i+1}: '{part}' -> type: '{part_type}'")

        # Test the extraction
        result = cleaner._extract_authors(case)
        print(f"  Extract result: {result}")

        # Test full cleaning
        full_result = cleaner.clean_byline(case)
        print(f"  Full clean result: {full_result}")


if __name__ == "__main__":
    debug_failing_cases()
