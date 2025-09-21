#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def debug_specific_cases():
    """Debug the specific failing cases."""
    cleaner = BylineCleaner()
    
    print("Debugging Specific Cases")
    print("=" * 40)
    
    # Debug case 1: "2nd Copy Editor"
    test1 = "JENNIFER LEE, 2nd Copy Editor"
    print(f"Test 1: {test1}")
    
    # Check what type each part gets
    parts = test1.split(',')
    for i, part in enumerate(parts):
        part_type = cleaner._identify_part_type(part.strip())
        print(f"  Part {i}: '{part.strip()}' → {part_type}")
    
    result1 = cleaner.clean_byline(test1)
    print(f"  Final Result: {result1}")
    print()
    
    # Debug case 2: "Senior Editor II, Managing Director III"
    test2 = "Senior Editor II, Managing Director III"
    print(f"Test 2: {test2}")
    
    parts = test2.split(',')
    for i, part in enumerate(parts):
        part_type = cleaner._identify_part_type(part.strip())
        print(f"  Part {i}: '{part.strip()}' → {part_type}")
    
    result2 = cleaner.clean_byline(test2)
    print(f"  Final Result: {result2}")
    print()
    
    # Test the ordinal processing specifically
    print("Testing ordinal number processing:")
    ordinal_tests = ["2nd", "2nd Copy", "Copy Editor", "2nd Copy Editor"]
    for test in ordinal_tests:
        part_type = cleaner._identify_part_type(test)
        print(f"  '{test}' → {part_type}")


if __name__ == "__main__":
    debug_specific_cases()