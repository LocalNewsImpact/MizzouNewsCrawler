#!/usr/bin/env python3

"""
Show complete text that will be removed for a domain.
"""

import argparse
import logging
from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner


def show_removal_text():
    """Show complete text that would be removed for a domain."""
    parser = argparse.ArgumentParser(
        description="Show complete text that will be removed for a domain"
    )
    parser.add_argument('--domain', required=True, help='Domain to analyze')
    parser.add_argument('--sample-size', type=int, default=15, 
                       help='Number of articles to sample')
    parser.add_argument('--min-occurrences', type=int, default=3, 
                       help='Minimum occurrences to consider')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.WARNING)  # Less verbose
    
    cleaner = TwoPhaseContentCleaner(db_path='data/mizzou.db')
    
    print(f"Analyzing {args.domain} for removable text...")
    print(f"Sample: {args.sample_size} articles, Min occurrences: {args.min_occurrences}")
    
    results = cleaner.analyze_domain(args.domain, args.sample_size, 
                                   args.min_occurrences)
    
    if not results['segments']:
        print("No duplicate segments found for removal.")
        return
    
    stats = results['stats']
    print(f"\n=== REMOVAL SUMMARY ===")
    print(f"Articles analyzed: {results['article_count']}")
    print(f"Removable segments: {len(results['segments'])}")
    print(f"Total removable characters: {stats['total_removable_chars']:,}")
    print(f"Removal percentage: {stats['removal_percentage']:.1f}%")
    
    print(f"\n=== COMPLETE REMOVABLE TEXT ===")
    print("=" * 80)
    
    total_chars = 0
    for i, segment in enumerate(results['segments'], 1):
        print(f"\n[SEGMENT {i}] - {segment['pattern_type'].upper()}")
        print(f"Length: {segment['length']} chars | Occurrences: {segment['occurrences']} articles")
        print(f"Position consistency: {segment['position_consistency']:.3f}")
        print("-" * 60)
        
        # Show the complete text with visible formatting
        text = segment['text']
        
        # Replace invisible characters with visible markers
        display_text = text.replace('\n', '\\n\n').replace('\t', '\\t').replace('\r', '\\r')
        
        print(display_text)
        print("-" * 60)
        
        total_chars += segment['length'] * segment['occurrences']
    
    print(f"\n=== TOTAL IMPACT ===")
    print(f"Total characters that would be removed: {total_chars:,}")
    print(f"Unique segments: {len(results['segments'])}")
    print(f"Average segment length: {sum(s['length'] for s in results['segments']) // len(results['segments'])} chars")
    
    # Show which articles would be affected
    affected_articles = set()
    for segment in results['segments']:
        affected_articles.update(segment['article_ids'])
    
    print(f"\nAffected articles ({len(affected_articles)}):")
    for i, article_id in enumerate(list(affected_articles)[:10], 1):
        print(f"  {i}. {article_id}")
    if len(affected_articles) > 10:
        print(f"  ... and {len(affected_articles) - 10} more")


if __name__ == "__main__":
    show_removal_text()