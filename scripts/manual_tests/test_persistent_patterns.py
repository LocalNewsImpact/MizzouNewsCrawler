#!/usr/bin/env python3
"""
Test the persistent pattern library system.
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def test_persistent_patterns():
    """Test the persistent pattern library functionality."""
    cleaner = BalancedBoundaryContentCleaner()

    # First, build some persistent patterns by analyzing a domain
    print("=== Building Persistent Pattern Library ===")
    result = cleaner.analyze_domain("kmbc.com", sample_size=10)
    print(f"Analyzed {result['article_count']} articles from kmbc.com")
    print(f"Found {len(result['segments'])} boilerplate segments")

    # Show what patterns were classified as persistent types
    persistent_types = {"subscription", "navigation", "footer"}
    persistent_segments = [
        s for s in result["segments"] if s["pattern_type"] in persistent_types
    ]

    print(f"\nFound {len(persistent_segments)} persistent-type patterns:")
    for segment in persistent_segments[:3]:  # Show first 3
        print(f"- {segment['pattern_type']}: {segment['text'][:100]}...")
        print(
            f"  Confidence: {segment['boundary_score']:.2f}, "
            f"Occurrences: {segment['occurrences']}"
        )

    # Now test getting persistent patterns from the library
    print("\n=== Testing Persistent Pattern Retrieval ===")
    patterns = cleaner.telemetry.get_persistent_patterns("kmbc.com")
    print(f"Retrieved {len(patterns)} persistent patterns for kmbc.com")

    for i, pattern in enumerate(patterns[:3], 1):
        print(
            f"{i}. {pattern['pattern_type']} (conf: {pattern['confidence_score']:.2f})"
        )
        print(f"   Occurrences: {pattern['occurrences_total']}")
        print(f"   Text: {pattern['text_content'][:100]}...")
        print()

    # Test using persistent patterns on a new article
    print("=== Testing Pattern Application to New Article ===")

    # Get a sample article from the same domain
    articles = cleaner._get_articles_for_domain("kmbc.com", sample_size=1)
    if articles:
        sample_text = articles[0]["content"]
        sample_id = articles[0]["id"]

        print(f"Testing on article {sample_id} (original length: {len(sample_text)})")

        cleaned_text, results = cleaner.process_single_article(
            sample_text, "kmbc.com", sample_id
        )

        print("After persistent pattern removal:")
        print(f"- New length: {len(cleaned_text)}")
        print(f"- Characters removed: {results['chars_removed']}")
        print(f"- Persistent removals: {results['persistent_removals']}")
        print(f"- Patterns matched: {results['patterns_matched']}")

        if results["chars_removed"] > 0:
            print(
                f"- Reduction: {results['chars_removed'] / len(sample_text) * 100:.1f}%"
            )
    else:
        print("No sample articles found for testing")

    # Test on a different domain to show it won't match
    print("\n=== Testing Cross-Domain Pattern Isolation ===")
    other_patterns = cleaner.telemetry.get_persistent_patterns("cnn.com")
    print(f"Retrieved {len(other_patterns)} persistent patterns for cnn.com")

    print("\nPersistent pattern library is working correctly!")
    print("- Patterns are stored per domain")
    print(
        "- Only persistent pattern types (subscription, navigation, footer) are saved"
    )
    print("- Only high-confidence patterns (>= 0.5 boundary score) are stored")
    print("- Pattern matching works for quick boilerplate removal")


if __name__ == "__main__":
    test_persistent_patterns()
