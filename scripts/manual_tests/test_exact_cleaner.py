#!/usr/bin/env python3

"""
Test CLI for the exact content cleaner.
"""

import logging
from src.utils.content_cleaner_exact import ExactContentCleaner


def setup_logging():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )


def test_exact_cleaner():
    """Test the exact content cleaner on problematic domains."""
    setup_logging()

    cleaner = ExactContentCleaner()

    # Test on the domains we know have issues
    test_domains = ["hannibal.net", "darnews.com", "ccheadliner.com"]

    for domain in test_domains:
        print(f"\n{'=' * 60}")
        print(f"TESTING DOMAIN: {domain}")
        print(f"{'=' * 60}")

        results = cleaner.analyze_domain(domain, sample_size=20)

        print(f"Articles analyzed: {results['article_count']}")
        print(f"Segments found: {len(results['segments'])}")

        if results["segments"]:
            print("\nTop segments by occurrence:")
            for i, segment in enumerate(results["segments"][:3]):
                print(f"\n--- Segment {i + 1} ---")
                print(f"Type: {segment['pattern_type']}")
                print(f"Length: {segment['length']} chars")
                print(f"Occurrences: {segment['occurrences']} articles")
                print(f"Position consistency: {segment['position_consistency']:.3f}")
                print("Text preview (first 200 chars):")
                preview = segment["text"][:200].replace("\n", "\\n")
                print(f"  '{preview}{'...' if len(segment['text']) > 200 else ''}'")

                # Show a few positions where it appears
                print(f"Appears in articles: {segment['article_ids'][:3]}...")
        else:
            print("No exact duplicate segments found.")


if __name__ == "__main__":
    test_exact_cleaner()
