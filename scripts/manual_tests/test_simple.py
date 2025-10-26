#!/usr/bin/env python3
"""
Simple test to see if persistent patterns are working.
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def test_simple():
    """Simple test of persistent patterns."""
    cleaner = BalancedBoundaryContentCleaner()

    # Check what persistent patterns we have
    patterns = cleaner.telemetry.get_persistent_patterns("www.douglascountyherald.com")
    print(f"Found {len(patterns)} persistent patterns for douglascountyherald.com")

    for i, pattern in enumerate(patterns[:3], 1):
        print(
            f"{i}. {pattern['pattern_type']} (conf: {pattern['confidence_score']:.2f})"
        )
        print(f"   Text: {pattern['text_content'][:80]}...")

    # Test single article processing
    articles = cleaner._get_articles_for_domain(
        "www.douglascountyherald.com", sample_size=1
    )
    if articles:
        sample_text = articles[0]["content"]
        sample_id = articles[0]["id"]

        print(f"\nTesting on article {sample_id}")
        print(f"Original length: {len(sample_text)}")

        cleaned_text, results = cleaner.process_single_article(
            sample_text, "www.douglascountyherald.com", sample_id
        )

        print(f"After processing: {len(cleaned_text)}")
        print(f"Results: {results}")


if __name__ == "__main__":
    test_simple()
