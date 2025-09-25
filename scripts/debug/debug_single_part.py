#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def debug_single_part():
    """Debug processing of a single part."""
    cleaner = BylineCleaner()
    
    test = "Senior Editor II"
    print(f"Debugging single part: {test}")
    
    # Test the full cleaning process
    result = cleaner.clean_byline(test)
    print(f"Result: {result}")
    
    # Test individual methods
    print(f"Part type: {cleaner._identify_part_type(test)}")
    print(f"Has name patterns: {cleaner._has_name_patterns(test)}")
    
    # Test normalization
    normalized = cleaner._normalize_capitalization(test)
    print(f"Normalized: '{normalized}'")


if __name__ == "__main__":
    debug_single_part()