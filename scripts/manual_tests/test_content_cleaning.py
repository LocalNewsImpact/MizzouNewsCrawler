#!/usr/bin/env python3
"""
Test script for content cleaning functionality.

This script demonstrates the content cleaning system by analyzing
domains for boilerplate content and testing removal.
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils.content_cleaner_final import ContentCleaner

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def main():
    """Demonstrate content cleaning functionality."""
    print("Content Cleaning System Demo")
    print("=" * 50)

    # Initialize cleaner
    db_path = "data/mizzou.db"
    cleaner = ContentCleaner(db_path=db_path, confidence_threshold=0.5)

    # Test domains
    test_domains = [
        "abc17news.com",
        "www.newspressnow.com",
        "www.douglascountyherald.com",
    ]

    for domain in test_domains:
        print(f"\nAnalyzing domain: {domain}")
        print("-" * 30)

        try:
            analysis = cleaner.analyze_domain(domain, sample_size=30)

            print(f"Articles analyzed: {analysis['articles']}")
            print(f"Boilerplate segments found: {analysis['boilerplate_segments']}")

            if analysis["segments"]:
                print("\nTop patterns:")
                for i, segment in enumerate(analysis["segments"][:3], 1):
                    print(f"{i}. Confidence: {segment['confidence_score']:.3f}")
                    print(f"   Occurrences: {segment['occurrence_count']}")
                    print(
                        f"   Position: {segment['avg_position']['start']:.1%} - {segment['avg_position']['end']:.1%}"
                    )
                    print(f"   Text: {segment['text'][:150]}...")
                    print()
            else:
                print("No significant boilerplate patterns detected")

        except Exception as e:
            print(f"Error analyzing {domain}: {e}")
            import traceback

            traceback.print_exc()

    print("\nContent cleaning analysis complete!")


if __name__ == "__main__":
    main()
