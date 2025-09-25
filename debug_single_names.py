#!/usr/bin/env python3

"""Debug specific failing cases."""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner

def debug_specific_cases():
    """Debug the specific failing cases."""
    
    cleaner = BylineCleaner(enable_telemetry=False)
    
    failing_cases = ["McDonald's", "Prince"]
    
    for case in failing_cases:
        print(f"Debugging: '{case}'")
        print("-" * 30)
        
        # Check part type
        part_type = cleaner._identify_part_type(case)
        print(f"Part type: {part_type}")
        
        # Check if it would pass validation
        words = case.split()
        print(f"Words: {words}")
        print(f"Length: {len(case)}")
        print(f"Has letters: {any(c.isalpha() for c in case)}")
        
        if len(words) == 1:
            word_lower = words[0].lower()
            print(f"Single word (lowercase): '{word_lower}'")
            print(f"In TITLES_TO_REMOVE: {word_lower in cleaner.TITLES_TO_REMOVE}")
            print(f"In JOURNALISM_NOUNS: {word_lower in cleaner.JOURNALISM_NOUNS}")
        
        # Test the full pipeline
        result = cleaner.clean_byline(case)
        print(f"Final result: {result}")
        
        # Step through manually
        print("\nStep-by-step:")
        print(f"1. _identify_part_type('{case}') = '{part_type}'")
        
        # Simulate _extract_authors logic
        if part_type in ['title', 'photo_credit']:
            print(f"2. Would be filtered out due to type '{part_type}'")
        else:
            print(f"2. Would be passed to validation")
            
            # Test validation
            valid = cleaner._validate_authors([case])
            print(f"3. _validate_authors(['{case}']) = {valid}")
        
        print("\n" + "=" * 50 + "\n")

if __name__ == "__main__":
    debug_specific_cases()