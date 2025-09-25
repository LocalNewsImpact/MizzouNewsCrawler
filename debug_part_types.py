#!/usr/bin/env python3
"""
Test the _identify_part_type method to see how it handles apostrophes.
"""

from src.utils.byline_cleaner import BylineCleaner


def test_part_type_identification():
    """Test how part type identification works with apostrophes."""
    cleaner = BylineCleaner()
    
    test_cases = [
        "O'Connor",
        "Sean", 
        "O'Brien",
        "Mary",
        "D'Angelo",
        "Staff Reporter",
        "News Editor",
        "photographer@news.com"
    ]
    
    print("🔍 TESTING PART TYPE IDENTIFICATION")
    print("=" * 60)
    
    for case in test_cases:
        part_type = cleaner._identify_part_type(case)
        print(f"'{case}' -> type: '{part_type}'")
    
    print("\n🧪 TESTING COMMA SPLIT BEHAVIOR")
    print("=" * 60)
    
    # Test the problematic cases
    problematic_cases = [
        "O'Connor, Sean",
        "O'brien, Mary Jane",
        "Sean O'Connor, Staff Reporter"
    ]
    
    for case in problematic_cases:
        print(f"\nTesting: '{case}'")
        
        # Split on comma
        comma_parts = case.split(',')
        print(f"  Comma parts: {comma_parts}")
        
        # Identify each part
        part_types = []
        for part in comma_parts:
            part_type = cleaner._identify_part_type(part.strip())
            part_types.append((part.strip(), part_type))
            print(f"    '{part.strip()}' -> '{part_type}'")
        
        # Test the actual extraction method
        result = cleaner._extract_authors(case)
        print(f"  Extract authors result: {result}")


if __name__ == "__main__":
    test_part_type_identification()