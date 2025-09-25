#!/usr/bin/env python3
"""
CLI tool to view ML training vs telemetry patterns.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner

def show_pattern_analysis(domain=None, show_ml_only=False, show_dynamic=True):
    """Show pattern analysis with ML training distinction."""
    cleaner = BalancedBoundaryContentCleaner()
    
    if domain:
        print(f"🔍 Pattern Analysis for: {domain}")
        print("=" * 60)
        
        # Get all patterns for this domain
        all_patterns = cleaner.telemetry.get_telemetry_patterns(domain)
        
        if not all_patterns:
            print(f"❌ No patterns found for {domain}")
            return
        
        ml_eligible = [p for p in all_patterns if p['is_ml_training_eligible']]
        dynamic_only = [p for p in all_patterns if not p['is_ml_training_eligible']]
        
        print("📊 Pattern Summary:")
        print(f"   Total patterns: {len(all_patterns)}")
        print(f"   ML Training eligible: {len(ml_eligible)}")
        print(f"   Dynamic (telemetry only): {len(dynamic_only)}")
        print()
        
        if show_ml_only or not show_dynamic:
            # Show only ML training patterns
            print("✅ ML TRAINING PATTERNS (Persistent):")
            print("-" * 40)
            if ml_eligible:
                for i, pattern in enumerate(ml_eligible, 1):
                    print(f"{i}. {pattern['pattern_type'].upper()}")
                    print(f"   Confidence: {pattern['confidence_score']:.2f}")
                    print(f"   Occurrences: {pattern['occurrences_total']}")
                    print(f"   Text: {pattern['text_content'][:80]}...")
                    print()
            else:
                print("   No ML training patterns found")
                print("   (subscription, navigation, footer types only)")
        
        if show_dynamic and not show_ml_only:
            print("\n🔍 TELEMETRY PATTERNS (Includes Dynamic):")
            print("-" * 40)
            for i, pattern in enumerate(dynamic_only[:10], 1):  # Show max 10
                status = "✅ ML" if pattern['is_ml_training_eligible'] else "🔍 Telemetry"
                print(f"{i}. {status} | {pattern['pattern_type'].upper()}")
                print(f"   Confidence: {pattern['confidence_score']:.2f}")
                print(f"   Occurrences: {pattern['occurrences_total']}")
                print(f"   Text: {pattern['text_content'][:60]}...")
                print()
    
    else:
        # Cross-domain analysis
        print("🌐 CROSS-DOMAIN PATTERN ANALYSIS")
        print("=" * 60)
        
        ml_patterns = cleaner.telemetry.get_ml_training_patterns()
        all_patterns = cleaner.telemetry.get_telemetry_patterns()
        
        domains_with_ml = set(p['domain'] for p in ml_patterns)
        domains_with_patterns = set(p['domain'] for p in all_patterns)
        
        print("📊 Global Pattern Summary:")
        print(f"   Domains with any patterns: {len(domains_with_patterns)}")
        print(f"   Domains with ML training patterns: {len(domains_with_ml)}")
        print(f"   Total ML training patterns: {len(ml_patterns)}")
        print(f"   Total patterns (all types): {len(all_patterns)}")
        print()
        
        if domains_with_ml:
            print("✅ DOMAINS WITH ML TRAINING PATTERNS:")
            print("-" * 40)
            for domain in sorted(domains_with_ml)[:10]:
                domain_patterns = [p for p in ml_patterns if p['domain'] == domain]
                print(f"   {domain}: {len(domain_patterns)} patterns")
        
        print("\n🔍 DOMAINS WITH TELEMETRY PATTERNS:")
        print("-" * 40)
        for domain in sorted(domains_with_patterns)[:10]:
            domain_patterns = [p for p in all_patterns if p['domain'] == domain]
            ml_count = sum(1 for p in domain_patterns if p['is_ml_training_eligible'])
            dynamic_count = len(domain_patterns) - ml_count
            print(f"   {domain}: {len(domain_patterns)} total ({ml_count} ML + {dynamic_count} dynamic)")

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="View ML training vs telemetry patterns"
    )
    parser.add_argument(
        'domain', nargs='?', 
        help='Domain to analyze (omit for cross-domain view)'
    )
    parser.add_argument(
        '--ml-only', action='store_true',
        help='Show only ML training eligible patterns'
    )
    parser.add_argument(
        '--no-dynamic', action='store_true',
        help='Hide dynamic patterns'
    )
    
    args = parser.parse_args()
    
    show_pattern_analysis(
        domain=args.domain,
        show_ml_only=args.ml_only,
        show_dynamic=not args.no_dynamic
    )

if __name__ == "__main__":
    main()