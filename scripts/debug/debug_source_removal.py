#!/usr/bin/env python3
"""Debug the source name removal for Mary Johnson case."""

import sys
import os

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.byline_cleaner import BylineCleaner

def debug_source_removal():
    """Debug the source name removal."""
    cleaner = BylineCleaner(enable_telemetry=False)
    
    # Test the individual steps
    byline = "By Mary Johnson Special to The Times"
    source_name = "The Times"
    
    print(f"Original byline: {byline}")
    print(f"Source name: {source_name}")
    
    # Step 1: Extract special contributor
    special_result = cleaner._extract_special_contributor(byline)
    print(f"1. Special extraction: '{special_result}'")
    
    # Step 2: Test source name removal
    if special_result:
        source_removed = cleaner._remove_source_name(special_result, source_name)
        print(f"2. After source removal: '{source_removed}'")
        
        # Step 3: Test publication name check
        is_pub = cleaner._is_publication_name(source_removed)
        print(f"3. Is publication name: {is_pub}")
        
        # Step 4: Test individual name cleaning
        if source_removed:
            cleaned_name = cleaner._clean_author_name(source_removed)
            print(f"4. After name cleaning: '{cleaned_name}'")

if __name__ == "__main__":
    debug_source_removal()