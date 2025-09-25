#!/usr/bin/env python3

"""
Debug the specific problematic segment.
"""

import logging
from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner


def debug_segment():
    """Debug the specific segment that's causing issues."""
    logging.basicConfig(level=logging.INFO)
    
    cleaner = TwoPhaseContentCleaner()
    
    # Get the full analysis
    results = cleaner.analyze_domain("hannibal.net", sample_size=10)
    
    if results['segments']:
        # Look at the first segment (the problematic one)
        segment = results['segments'][0]
        
        print("PROBLEMATIC SEGMENT ANALYSIS:")
        print(f"Length: {segment['length']}")
        print(f"Occurrences: {segment['occurrences']}")
        print(f"Position consistency: {segment['position_consistency']:.3f}")
        
        print(f"\nFULL TEXT:")
        print(f"'{segment['text']}'")
        
        print(f"\nAPPEARS IN ARTICLES:")
        for article_id in segment['article_ids']:
            print(f"  - {article_id}")
        
        # Show some positions
        print(f"\nPOSITIONS:")
        for article_id, positions in list(segment['positions'].items())[:3]:
            print(f"  Article {article_id}: {positions}")


if __name__ == "__main__":
    debug_segment()