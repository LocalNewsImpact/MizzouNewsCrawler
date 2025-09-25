#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def compare_implementations():
    """Compare my trace with the actual method."""
    cleaner = BylineCleaner()
    
    part = "ROBERT DAVIS III"
    print(f"Testing: {part}")
    
    # Call the actual method
    actual_result = cleaner._identify_part_type(part)
    print(f"Actual method result: {actual_result}")
    
    # Also test the exact input from debug
    part2 = "ROBERT DAVIS III"  # Same but just to be sure
    actual_result2 = cleaner._identify_part_type(part2)
    print(f"Second test result: {actual_result2}")
    
    # Test with stripped version
    part3 = part.strip()
    actual_result3 = cleaner._identify_part_type(part3)
    print(f"Stripped test result: {actual_result3}")


if __name__ == "__main__":
    compare_implementations()