#!/usr/bin/env python3

"""
Test the proper boundary content cleaner.
"""

import logging
from src.utils.content_cleaner_proper_boundaries import ProperBoundaryContentCleaner


def test_proper_boundaries():
    """Test the proper boundary content cleaner."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    cleaner = ProperBoundaryContentCleaner()

    # Test on hannibal.net
    domain = "hannibal.net"
    print(f"\n{'=' * 60}")
    print(f"TESTING DOMAIN: {domain} (with proper boundaries)")
    print(f"{'=' * 60}")

    results = cleaner.analyze_domain(domain, sample_size=10)

    print(f"Articles analyzed: {results['article_count']}")
    print(f"Segments found: {len(results['segments'])}")

    if results["segments"]:
        stats = results["stats"]
        print(f"Affected articles: {stats['affected_articles']}")
        print(f"Removal percentage: {stats['removal_percentage']:.1f}%")

        print("\nProperly bounded segments:")
        for i, segment in enumerate(results["segments"][:5], 1):
            print(f"\n--- Segment {i} ---")
            print(f"Type: {segment['pattern_type']}")
            print(f"Length: {segment['length']} chars")
            print(f"Occurrences: {segment['occurrences']} articles")
            print(f"Position consistency: {segment['position_consistency']:.3f}")

            # Show the complete text
            text = segment["text"]
            print("Complete text:")
            print(f"  START: '{text[:50]}...'")
            print(f"  END:   '...{text[-50:]}'")

            # Check if it's properly bounded
            if text.strip():
                starts_properly = text[0].isupper() or text[0] in "\"'"
                ends_properly = text.strip()[-1] in ".!?:"
                print(f"  Proper start: {starts_properly}")
                print(f"  Proper end: {ends_properly}")
    else:
        print("No properly bounded segments found.")


if __name__ == "__main__":
    test_proper_boundaries()
