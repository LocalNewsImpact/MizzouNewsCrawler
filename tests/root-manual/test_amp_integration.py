#!/usr/bin/env python3
"""
Test AMP bypass integration in ContentExtractor.

This script tests the automatic AMP bypass for PerimeterX-protected sites.
"""

import logging
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from src.crawler import ContentExtractor

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Test URLs - known PerimeterX sites
TEST_URLS = [
    "https://fox4kc.com/news/local-news/kc-firefighters-rescue-2-from-burning-home-in-northeast-kansas-city/",
    "https://www.fourstateshomepage.com/news/local-news/joplin-news/new-pickleball-complex-coming-to-joplin/",
]


def test_amp_bypass():
    """Test AMP bypass for PerimeterX sites."""

    logger.info("=" * 80)
    logger.info("Testing AMP bypass integration")
    logger.info("=" * 80)

    extractor = ContentExtractor()

    for url in TEST_URLS:
        logger.info(f"\n{'='*80}")
        logger.info(f"Testing: {url}")
        logger.info(f"{'='*80}\n")

        try:
            result = extractor.extract(url)

            if result and result.get("content"):
                logger.info("✅ SUCCESS!")
                logger.info(f"Title: {result.get('title', 'N/A')[:80]}")
                logger.info(f"Content length: {len(result.get('content', ''))} chars")
                logger.info(
                    f"Extraction method: {result.get('metadata', {}).get('extraction_method', 'unknown')}"
                )
                logger.info(
                    f"HTTP status: {result.get('metadata', {}).get('http_status', 'unknown')}"
                )

                # Check if AMP was used
                amp_indicators = [
                    result.get("metadata", {}).get("amp_url"),
                    "amp" in str(result.get("metadata", {})).lower(),
                ]
                if any(amp_indicators):
                    logger.info("🎯 AMP bypass was used!")

                # Show first 200 chars of content
                content = result.get("content", "")
                if content:
                    logger.info(f"\nContent preview:\n{content[:200]}...")
            else:
                logger.error("❌ FAILED - No content extracted")
                if result:
                    logger.error(f"Error: {result.get('error', 'Unknown error')}")
                    logger.error(f"Metadata: {result.get('metadata', {})}")

        except Exception as e:
            logger.error(f"❌ EXCEPTION: {e}", exc_info=True)

    logger.info(f"\n{'='*80}")
    logger.info("Test complete!")
    logger.info(f"{'='*80}")


if __name__ == "__main__":
    test_amp_bypass()
