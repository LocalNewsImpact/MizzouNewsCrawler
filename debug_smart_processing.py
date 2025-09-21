#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def debug_smart_processing():
    """Debug the smart processing logic specifically."""
    cleaner = BylineCleaner()
    
    test = "Senior Editor II, Managing Director III"
    print(f"Debugging: {test}")
    
    # Manually walk through the logic
    comma_parts = test.split(',')
    print(f"Comma parts: {comma_parts}")
    
    part_types = []
    for part in comma_parts:
        part_type = cleaner._identify_part_type(part)
        part_types.append((part.strip(), part_type))
        print(f"  '{part.strip()}' → {part_type}")
    
    # Count different types
    non_name_count = sum(1 for _, ptype in part_types
                         if ptype in ['email', 'title'])
    print(f"Non-name count: {non_name_count}")
    
    # Smart processing condition
    condition = (non_name_count >= 2 or
                 (non_name_count >= 1 and len(comma_parts) >= 3))
    print(f"Smart processing condition: {condition}")
    
    if condition:
        # Find parts that are clearly names
        name_parts = [part for part, ptype in part_types
                      if ptype == 'name']
        print(f"Name parts: {name_parts}")
        
        if name_parts:
            print("Would return name parts")
        else:
            print("No name parts, checking fallback...")
            # If no clear names, take the first part that's not email/title
            for part, ptype in part_types:
                print(f"  Checking '{part}' with type '{ptype}'")
                if ptype not in ['email', 'title'] and part:
                    print(f"  Would return: {part}")
                    break
            else:
                print("  No fallback found, would use first part")
                first_part = comma_parts[0].strip()
                print(f"  First part: '{first_part}'")
    
    # Now run the actual method
    result = cleaner.clean_byline(test)
    print(f"Actual result: {result}")


if __name__ == "__main__":
    debug_smart_processing()