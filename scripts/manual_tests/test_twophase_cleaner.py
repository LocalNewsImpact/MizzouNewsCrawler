#!/usr/bin/env python3

"""
Test the two-phase content cleaner.
"""

import logging
from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner


def test_twophase_cleaner():
    """Test the two-phase content cleaner on problematic domains."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    cleaner = TwoPhaseContentCleaner()

    # Test on hannibal.net first (the problematic one)
    domain = "hannibal.net"
    print(f"\n{'=' * 60}")
    print(f"TESTING DOMAIN: {domain}")
    print(f"{'=' * 60}")

    results = cleaner.analyze_domain(domain, sample_size=10)

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
            print("Text preview (first 150 chars):")
            preview = segment["text"][:150].replace("\n", "\\n")
            print(f"  '{preview}{'...' if len(segment['text']) > 150 else ''}'")
    else:
        print("No exact duplicate segments found.")


if __name__ == "__main__":
    test_twophase_cleaner()
