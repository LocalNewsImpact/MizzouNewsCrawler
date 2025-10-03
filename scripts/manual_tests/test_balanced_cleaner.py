#!/usr/bin/env python3
"""
Test script for the balanced boundary content cleaner.
"""

import sys
import argparse
import logging
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def main():
    parser = argparse.ArgumentParser(
        description="Test balanced boundary content cleaner"
    )
    parser.add_argument("--domain", required=True, help="Domain to analyze")
    parser.add_argument(
        "--sample-size", type=int, default=20, help="Number of articles to sample"
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=3,
        help="Minimum occurrences for detection",
    )
    parser.add_argument(
        "--show-text", action="store_true", help="Show full text of segments"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s:%(name)s:%(message)s")

    # Run analysis
    cleaner = BalancedBoundaryContentCleaner()
    result = cleaner.analyze_domain(args.domain, args.sample_size, args.min_occurrences)

    print(f"Domain: {result['domain']}")
    print(f"Articles analyzed: {result['article_count']}")
    print(f"Segments found: {len(result['segments'])}")

    if "stats" in result:
        stats = result["stats"]
        print(f"Affected articles: {stats['affected_articles']}")
        print(f"Total removable characters: {stats['total_removable_chars']:,}")
        print(f"Removal percentage: {stats['removal_percentage']:.1f}%")

    if result["segments"]:
        print("\nDetected segments:")
        print("=" * 60)

        for i, segment in enumerate(result["segments"], 1):
            print(f"{i}. Pattern: {segment['pattern_type']}")
            print(f"   Occurrences: {segment['occurrences']}")
            print(f"   Length: {segment['length']} chars")
            print(f"   Boundary score: {segment['boundary_score']:.2f}")

            if args.show_text:
                print(f'   Text: "{segment["text"]}"')
            else:
                preview = segment["text"][:100]
                suffix = "..." if len(segment["text"]) > 100 else ""
                print(f'   Preview: "{preview}{suffix}"')

            print()
    else:
        print("No boilerplate segments detected.")


if __name__ == "__main__":
    main()
