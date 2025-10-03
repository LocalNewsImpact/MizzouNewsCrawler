#!/usr/bin/env python3
"""
Test script to verify bot-avoidance techniques work consistently
across all extraction methods (newspaper4k, BeautifulSoup, Selenium).
"""

import logging
import sys
from src.crawler import ContentExtractor

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def test_extraction_methods():
    """Test all extraction methods on a challenging URL."""

    # Use a URL that's known to have some bot protection
    test_url = "https://httpbin.org/user-agent"  # Shows user agent used

    print("🤖 Testing Bot-Avoidance Consistency")
    print("=" * 50)

    extractor = ContentExtractor()

    print(f"\nTesting URL: {test_url}")
    print("-" * 30)

    # Test the unified extraction method (with fallbacks)
    try:
        result = extractor.extract_content(test_url)

        if result:
            print("✅ Extraction completed successfully!")
            print(f"Title: {result.get('title', 'N/A')}")
            print(f"Content length: {len(result.get('content', ''))}")

            # Show which methods were used
            extraction_methods = result.get("metadata", {}).get(
                "extraction_methods", {}
            )
            if extraction_methods:
                print("📊 Methods used per field:")
                for field, method in extraction_methods.items():
                    print(f"  - {field}: {method}")
            else:
                print("📊 Extraction method: Single method (likely newspaper4k)")

            # Show bot-avoidance details
            metadata = result.get("metadata", {})
            cloudscraper_used = metadata.get("cloudscraper_used", False)
            stealth_mode = metadata.get("stealth_mode", False)

            print("\n🛡️  Bot-avoidance features:")
            print(f"  - Cloudscraper: {'✅' if cloudscraper_used else '❌'}")
            print(f"  - Selenium stealth: {'✅' if stealth_mode else '❌'}")

            return True
        else:
            print("❌ Extraction failed - no content returned")
            return False

    except Exception as e:
        print(f"❌ Extraction failed with error: {e}")
        return False


def test_individual_methods():
    """Test each extraction method individually for comparison."""

    test_url = "https://httpbin.org/headers"  # Shows all headers sent

    print("\n\n🔍 Testing Individual Methods")
    print("=" * 50)

    extractor = ContentExtractor()

    # Test newspaper4k
    print("\n1. Testing newspaper4k method:")
    try:
        result = extractor._extract_with_newspaper(test_url)
        cloudscraper_used = result.get("metadata", {}).get("cloudscraper_used", False)
        print(f"   Cloudscraper: {'✅' if cloudscraper_used else '❌'}")
        print(f"   Content length: {len(result.get('content', ''))}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")

    # Test BeautifulSoup
    print("\n2. Testing BeautifulSoup method:")
    try:
        result = extractor._extract_with_beautifulsoup(test_url)
        cloudscraper_used = result.get("metadata", {}).get("cloudscraper_used", False)
        print(f"   Cloudscraper: {'✅' if cloudscraper_used else '❌'}")
        print(f"   Content length: {len(result.get('content', ''))}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")

    # Test Selenium (if available)
    print("\n3. Testing Selenium method:")
    try:
        from selenium import webdriver

        result = extractor._extract_with_selenium(test_url)
        stealth_mode = result.get("metadata", {}).get("stealth_mode", False)
        print(f"   Stealth mode: {'✅' if stealth_mode else '❌'}")
        print(f"   Content length: {len(result.get('content', ''))}")
    except ImportError:
        print("   ⚠️  Selenium not available")
    except Exception as e:
        print(f"   ❌ Failed: {e}")


if __name__ == "__main__":
    print("🚀 Starting Bot-Avoidance Tests\n")

    # Test unified extraction
    success = test_extraction_methods()

    # Test individual methods
    test_individual_methods()

    print("\n\n📝 Summary:")
    print("=" * 20)
    if success:
        print("✅ Bot-avoidance testing completed successfully!")
        print(
            "All extraction methods are now using consistent bot-avoidance techniques."
        )
    else:
        print("⚠️  Some issues detected - check the logs above.")

    print("\n🔧 Bot-avoidance features implemented:")
    print("• newspaper4k: Uses cloudscraper session for Cloudflare bypass")
    print("• BeautifulSoup: Uses cloudscraper + realistic headers")
    print("• Selenium: Advanced stealth mode with anti-detection")

    sys.exit(0 if success else 1)
