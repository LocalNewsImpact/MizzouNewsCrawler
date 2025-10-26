#!/usr/bin/env python3

"""
Test the two-phase cleaner on all our problematic domains.
"""

import logging
from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner


def test_all_domains():
    """Test the two-phase cleaner on multiple domains."""
    logging.basicConfig(level=logging.WARNING)  # Less verbose

    cleaner = TwoPhaseContentCleaner()

    test_domains = ["hannibal.net", "darnews.com", "ccheadliner.com"]

    for domain in test_domains:
        print(f"\n{'=' * 60}")
        print(f"DOMAIN: {domain}")
        print(f"{'=' * 60}")

        results = cleaner.analyze_domain(domain, sample_size=15)

        print(f"Articles: {results['article_count']}")
        print(f"Segments found: {len(results['segments'])}")

        if results["segments"]:
            stats = results["stats"]
            print(f"Affected articles: {stats['affected_articles']}")
            print(f"Removal percentage: {stats['removal_percentage']:.1f}%")

            print("\nTop segments:")
            for i, segment in enumerate(results["segments"][:3]):
                print(
                    f"\n{i + 1}. [{segment['pattern_type']}] "
                    f"{segment['occurrences']} articles, "
                    f"{segment['length']} chars, "
                    f"consistency: {segment['position_consistency']:.2f}"
                )

                # Show preview
                preview = segment["text"][:100].replace("\n", "\\n")
                print(f"   '{preview}{'...' if len(segment['text']) > 100 else ''}'")
        else:
            print("No duplicate segments found.")


if __name__ == "__main__":
    test_all_domains()
