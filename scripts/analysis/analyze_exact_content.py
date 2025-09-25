#!/usr/bin/env python3

"""
Standalone script to test exact content cleaning analysis.
"""

import argparse
import logging
from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner


def main():
    parser = argparse.ArgumentParser(
        description="Analyze domains for exact duplicate text segments"
    )
    parser.add_argument('--domain', required=True, help='Domain to analyze')
    parser.add_argument('--sample-size', type=int, default=20, 
                       help='Number of articles to sample')
    parser.add_argument('--min-occurrences', type=int, default=3, 
                       help='Minimum occurrences to consider')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show analysis without making changes')
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    cleaner = TwoPhaseContentCleaner(db_path='data/mizzou.db')
    
    print(f"Analyzing {args.domain} for exact duplicate segments...")
    print(f"Sample size: {args.sample_size}, "
          f"Min occurrences: {args.min_occurrences}")
    
    results = cleaner.analyze_domain(args.domain, args.sample_size, 
                                   args.min_occurrences)
    
    if not results['segments']:
        print("No exact duplicate segments found.")
        return
    
    stats = results['stats']
    print("\n=== ANALYSIS RESULTS ===")
    print(f"Articles analyzed: {results['article_count']}")
    print(f"Segments found: {len(results['segments'])}")
    print(f"Affected articles: {stats['affected_articles']}")
    print(f"Total removable characters: {stats['total_removable_chars']:,}")
    print(f"Removal percentage: {stats['removal_percentage']:.1f}%")
    
    print("\n=== EXACT DUPLICATE SEGMENTS ===")
    for i, segment in enumerate(results['segments'], 1):
        print(f"\n--- Segment {i} ---")
        print(f"Type: {segment['pattern_type']}")
        print(f"Length: {segment['length']} characters")
        print(f"Occurrences: {segment['occurrences']} articles")
        print(f"Position consistency: {segment['position_consistency']:.3f}")
        print(f"Article IDs: {', '.join(segment['article_ids'][:5])}...")
        
        # Show text preview
        preview = segment['text'][:200].replace('\n', '\\n')
        print(f"Text preview: "
              f"'{preview}{'...' if len(segment['text']) > 200 else ''}'")
        
        if args.dry_run:
            print("(DRY RUN - no changes made)")


if __name__ == "__main__":
    main()