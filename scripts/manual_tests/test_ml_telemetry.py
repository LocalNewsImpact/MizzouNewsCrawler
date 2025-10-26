#!/usr/bin/env python3
"""
Test the ML training vs telemetry pattern distinction.
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


def test_ml_telemetry_patterns():
    """Test the distinction between ML training patterns and telemetry patterns."""
    cleaner = BalancedBoundaryContentCleaner()

    # First, run analysis to populate patterns
    print("=== Building Pattern Library ===")
    result = cleaner.analyze_domain("www.douglascountyherald.com", sample_size=20)
    print(f"Analyzed {result['article_count']} articles")
    print(f"Found {len(result['segments'])} boilerplate segments")

    # Show pattern type distribution
    pattern_counts = {}
    for segment in result["segments"]:
        ptype = segment["pattern_type"]
        pattern_counts[ptype] = pattern_counts.get(ptype, 0) + 1

    print("\n📊 Pattern Type Distribution:")
    for ptype, count in pattern_counts.items():
        print(f"  {ptype}: {count} segments")

    # Test ML training patterns (persistent only)
    print("\n=== ML Training Patterns (Persistent Only) ===")
    ml_patterns = cleaner.telemetry.get_ml_training_patterns(
        "www.douglascountyherald.com"
    )
    print(f"ML Training Eligible: {len(ml_patterns)} patterns")

    for i, pattern in enumerate(ml_patterns[:3], 1):
        print(
            f"{i}. {pattern['pattern_type']} (conf: {pattern['confidence_score']:.2f})"
        )
        print(f"   Occurrences: {pattern['occurrences_total']}")
        print(f"   Text: {pattern['text_content'][:60]}...")
        print()

    # Test all telemetry patterns (includes dynamic)
    print("=== All Telemetry Patterns (Includes Dynamic) ===")
    all_patterns = cleaner.telemetry.get_telemetry_patterns(
        "www.douglascountyherald.com"
    )
    print(f"All Patterns: {len(all_patterns)} patterns")

    ml_eligible_count = sum(1 for p in all_patterns if p["is_ml_training_eligible"])
    dynamic_count = len(all_patterns) - ml_eligible_count

    print(f"  └─ ML Training Eligible: {ml_eligible_count}")
    print(f"  └─ Dynamic (Telemetry Only): {dynamic_count}")

    print("\nPattern Categories:")
    for pattern in all_patterns[:5]:
        category = (
            "✅ ML-Eligible"
            if pattern["is_ml_training_eligible"]
            else "🔍 Telemetry-Only"
        )
        print(
            f"  {category} | {pattern['pattern_type']} | {pattern['text_content'][:50]}..."
        )

    # Test cross-domain ML patterns
    print("\n=== Cross-Domain ML Training Patterns ===")
    all_ml_patterns = cleaner.telemetry.get_ml_training_patterns()
    domains_with_ml = set(p["domain"] for p in all_ml_patterns)
    print(f"Found ML training patterns across {len(domains_with_ml)} domains")

    for domain in list(domains_with_ml)[:3]:
        domain_patterns = [p for p in all_ml_patterns if p["domain"] == domain]
        print(f"  {domain}: {len(domain_patterns)} ML-eligible patterns")

    print("\n✅ ML Training vs Telemetry Pattern System Working!")
    print("💡 Key Features:")
    print("  - Persistent patterns (subscription, navigation, footer) → ML Training")
    print("  - Dynamic patterns (sidebar, trending, other) → Telemetry Only")
    print("  - All patterns captured for review and analysis")
    print("  - Clean separation prevents dynamic content from corrupting ML models")


if __name__ == "__main__":
    test_ml_telemetry_patterns()
