#!/usr/bin/env python3
"""Debug source name removal."""

import sys
import os

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.byline_cleaner import BylineCleaner


def debug_source_removal():
    """Debug source name removal."""
    cleaner = BylineCleaner(enable_telemetry=False)
    
    byline = "By Mary Johnson Special to The Times"
    source_name = "The Times"
    
    print(f"Original: {byline}")
    print(f"Source name: {source_name}")
    
    removed = cleaner._remove_source_name(byline, source_name)
    print(f"After source removal: '{removed}'")
    
    # Test special extraction on both
    special_before = cleaner._extract_special_contributor(byline)
    special_after = cleaner._extract_special_contributor(removed)
    
    print(f"Special extraction before source removal: '{special_before}'")
    print(f"Special extraction after source removal: '{special_after}'")


if __name__ == "__main__":
    debug_source_removal()