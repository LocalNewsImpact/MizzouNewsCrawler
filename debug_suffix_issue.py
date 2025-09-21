#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def debug_suffix_issue():
    """Debug the failing suffix case."""
    cleaner = BylineCleaner()
    
    test = "MARY JONES SR., Editor, ROBERT DAVIS III"
    print(f"Debugging: {test}")
    
    # Test the full cleaning process
    result = cleaner.clean_byline(test)
    print(f"Result: {result}")
    print(f"Expected: ['Mary Jones Sr.', 'Robert Davis III']")
    
    # Check part types
    comma_parts = test.split(',')
    print(f"Comma parts: {comma_parts}")
    
    for i, part in enumerate(comma_parts):
        part = part.strip()
        part_type = cleaner._identify_part_type(part)
        print(f"  Part {i+1}: '{part}' → {part_type}")


if __name__ == "__main__":
    debug_suffix_issue()