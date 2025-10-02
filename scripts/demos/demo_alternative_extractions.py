#!/usr/bin/env python3
"""
Demonstration of Alternative Extraction Tracking

This script shows how the enhanced telemetry system now tracks when later 
extraction methods find alternative values for fields that are already 
populated by earlier methods.
"""

import json

from src.utils.comprehensive_telemetry import ExtractionMetrics


def demo_alternative_tracking():
    """Demonstrate alternative extraction tracking."""

    print("=== ALTERNATIVE EXTRACTION TRACKING DEMO ===\n")

    # Create a metrics object
    metrics = ExtractionMetrics('demo-op', 'demo-article',
                              'https://example.com/article', 'example.com')

    print("📰 SCENARIO: Multi-method extraction with alternatives\n")

    # Simulate extraction results
    newspaper_result = {
        'title': 'Breaking: Stock Market Surges Today',
        'author': None,
        'content': None,
        'publish_date': '2025-09-23'
    }

    beautifulsoup_result = {
        'title': 'BREAKING NEWS: Market Hits Record High',  # Alternative title
        'author': 'Jane Smith',
        'content': 'The stock market reached unprecedented heights...',
        'publish_date': '2025-09-23T10:30:00'  # More precise time
    }

    selenium_result = {
        'title': 'Stock Market Soars to New Heights',  # Another alternative
        'author': 'John Doe',  # Alternative author
        'content': 'Market analysts are amazed by today\'s performance...',  # Alternative content
        'publish_date': '2025-09-23T10:30:00Z'  # Yet another format
    }

    # Simulate the extraction process
    target = {
        'title': None,
        'author': None,
        'content': None,
        'publish_date': None,
        'extraction_methods': {}
    }

    print("🔍 STEP 1: newspaper4k extraction")
    for field, value in newspaper_result.items():
        if field != 'extraction_methods' and value:
            target[field] = value
            target['extraction_methods'][field] = 'newspaper4k'
            print(f"   ✓ Extracted {field}: {value}")

    print(f"\n📊 Current state: {json.dumps(target, indent=2)}")

    print("\n🔍 STEP 2: BeautifulSoup fallback")
    for field, value in beautifulsoup_result.items():
        if field != 'extraction_methods' and value:
            current_value = target.get(field)
            if not current_value:
                target[field] = value
                target['extraction_methods'][field] = 'beautifulsoup'
                print(f"   ✓ Extracted {field}: {value}")
            else:
                # Record alternative extraction
                metrics.record_alternative_extraction(
                    'beautifulsoup', field, value, current_value
                )
                print(f"   🔄 Alternative {field} found: {value}")
                print(f"      (keeping current: {current_value})")

    print(f"\n📊 Current state: {json.dumps(target, indent=2)}")

    print("\n🔍 STEP 3: Selenium final fallback")
    for field, value in selenium_result.items():
        if field != 'extraction_methods' and value:
            current_value = target.get(field)
            if not current_value:
                target[field] = value
                target['extraction_methods'][field] = 'selenium'
                print(f"   ✓ Extracted {field}: {value}")
            else:
                # Record alternative extraction
                metrics.record_alternative_extraction(
                    'selenium', field, value, current_value
                )
                print(f"   🔄 Alternative {field} found: {value}")
                print(f"      (keeping current: {current_value})")

    print(f"\n📊 Final result: {json.dumps(target, indent=2)}")

    print("\n🎯 ALTERNATIVES CAPTURED:")
    print(json.dumps(metrics.alternative_extractions, indent=2))

    print("\n💡 INSIGHTS:")
    print("   • newspaper4k got the basic fields")
    print("   • BeautifulSoup found a different title format")
    print("   • Selenium found completely different content approaches")
    print("   • All alternatives are now tracked for analysis!")

    return metrics

if __name__ == "__main__":
    demo_alternative_tracking()
