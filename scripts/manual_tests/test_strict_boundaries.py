#!/usr/bin/env python3

"""
Test strict proper boundary filtering.
"""

import logging
from src.utils.content_cleaner_proper_boundaries import ProperBoundaryContentCleaner


def test_strict_boundaries():
    """Test with strict boundary requirements."""
    logging.basicConfig(level=logging.WARNING)  # Less verbose

    cleaner = ProperBoundaryContentCleaner()

    domain = "hannibal.net"
    results = cleaner.analyze_domain(domain, sample_size=10)

    print(f"ORIGINAL RESULTS: {len(results['segments'])} segments")

    # Filter to only properly bounded segments
    strict_segments = []
    for segment in results["segments"]:
        text = segment["text"].strip()
        if text:
            # Check proper start
            starts_properly = text[0].isupper() or text[0] in "\"'"
            # Check proper end
            ends_properly = text[-1] in ".!?:"

            if starts_properly and ends_properly:
                strict_segments.append(segment)
            else:
                print("\nREJECTED (improper boundaries):")
                print(f"  Length: {len(text)} chars")
                print(f"  Starts properly: {starts_properly}")
                print(f"  Ends properly: {ends_properly}")
                print(f"  Text: '{text[:100]}{'...' if len(text) > 100 else ''}'")

    print(f"\nSTRICT RESULTS: {len(strict_segments)} segments")

    if strict_segments:
        total_chars = sum(s["length"] * s["occurrences"] for s in strict_segments)
        print(
            f"Removal percentage with strict boundaries: {total_chars / sum(len(a['content']) for a in cleaner._get_articles_for_domain(domain, 10)) * 100:.1f}%"
        )

        print("\nSTRICT SEGMENTS (properly bounded):")
        for i, segment in enumerate(strict_segments, 1):
            text = segment["text"]
            print(
                f"\n{i}. [{segment['pattern_type']}] {segment['length']} chars, {segment['occurrences']} articles"
            )
            print(f"   Text: '{text}'")


if __name__ == "__main__":
    test_strict_boundaries()
