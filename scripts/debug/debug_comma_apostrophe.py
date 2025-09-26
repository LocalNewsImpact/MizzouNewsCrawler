#!/usr/bin/env python3
"""
Debug the specific apostrophe issue with comma-separated names.
"""

from src.utils.byline_cleaner import BylineCleaner


def debug_comma_apostrophe():
    """Debug the specific comma-separated apostrophe issue."""
    cleaner = BylineCleaner()
    
    test_cases = [
        "O'Connor, Sean",
        "O'brien, Mary Jane"
    ]
    
    print("🔍 DEBUGGING COMMA-SEPARATED APOSTROPHE NAMES")
    print("=" * 60)
    
    for test_case in test_cases:
        print(f"\nTesting: '{test_case}'")
        result = cleaner.clean_byline(test_case)
        print(f"Result: {result}")
        
        # Check each result for apostrophes
        for i, name in enumerate(result):
            has_apostrophe = "'" in name
            print(f"  Name {i+1}: '{name}' - Has apostrophe: {has_apostrophe}")
            
        # The real question: should "O'Connor, Sean" be one name or two?
        print(f"  Question: Should this be 1 name or {len(result)} names?")
        
        # Check if this could be "Last, First" format
        if len(result) == 2 and ',' in test_case:
            parts = test_case.split(',')
            if len(parts) == 2:
                first_part = parts[0].strip()
                second_part = parts[1].strip()
                print(
                    "  Could be 'Last, First': "
                    f"'{first_part}' (last), '{second_part}' (first)"
                )
                
                # Check if this looks like a "Last, First" pattern
                first_part_words = first_part.split()
                second_part_words = second_part.split()
                
                # If first part is 1 word (surname) and second part is
                # 1-2 words (given names)
                if (
                    len(first_part_words) == 1
                    and 1 <= len(second_part_words) <= 2
                ):
                    combined = f"{second_part} {first_part}"
                    print(f"  Combined as 'First Last': '{combined}'")
    
    print("\n📝 CONCLUSION:")
    print("The apostrophe is preserved correctly.")
    print("The issue is whether 'O'Connor, Sean' should be:")
    print("  Option 1: Two people - ['O'Connor', 'Sean']")
    print("  Option 2: One person - ['Sean O'Connor']")
    print("This depends on the desired behavior for 'Last, First' formats.")


if __name__ == "__main__":
    debug_comma_apostrophe()
