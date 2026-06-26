#!/usr/bin/env python3
"""Test discovery and extraction of ky3.com using CloudScraper."""

import sys
import logging
import json
from typing import Optional
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import cloudscraper
    logger.info("✓ CloudScraper imported successfully")
except ImportError:
    logger.error("✗ CloudScraper not installed. Install with: pip install cloudscraper")
    sys.exit(1)

try:
    from newspaper import Article
    logger.info("✓ Newspaper4k imported successfully")
except ImportError:
    logger.error("✗ Newspaper4k not installed. Install with: pip install newspaper4k")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
    logger.info("✓ BeautifulSoup imported successfully")
except ImportError:
    logger.error("✗ BeautifulSoup not installed. Install with: pip install beautifulsoup4")
    sys.exit(1)


class KY3CloudScraperTester:
    """Test CloudScraper with ky3.com discovery and extraction."""

    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.base_url = "https://www.ky3.com"
        self.discovered_urls = []
        self.extracted_articles = []

    def discover_urls(self, limit: int = 5) -> list[str]:
        """Discover article URLs from ky3.com using CloudScraper."""
        logger.info(f"🔍 Starting URL discovery for {self.base_url}")
        logger.info(f"   Target: {limit} articles")

        try:
            # Fetch homepage with CloudScraper
            logger.info(f"📡 Fetching homepage with CloudScraper...")
            response = self.scraper.get(
                self.base_url,
                timeout=10,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            response.raise_for_status()
            logger.info(f"   Status: {response.status_code}")

            # Parse HTML for article links
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find article links - KY3 uses /2026/MM/DD/ date pattern
            article_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                # Look for article URLs with date pattern
                if '/2026/' in href and href.startswith('/'):
                    full_url = self.base_url + href
                    if full_url not in article_links:
                        article_links.append(full_url)
                        if len(article_links) >= limit:
                            break

            logger.info(f"✓ Found {len(article_links)} article URLs")
            for i, url in enumerate(article_links, 1):
                logger.info(f"   {i}. {url}")

            self.discovered_urls = article_links
            return article_links

        except Exception as e:
            logger.error(f"✗ Discovery failed: {e}", exc_info=True)
            return []

    def extract_article(self, url: str) -> Optional[dict]:
        """Extract article content from URL using CloudScraper + Newspaper4k."""
        logger.info(f"📄 Extracting article: {url}")

        try:
            # Fetch with CloudScraper first (handles bot protection)
            logger.info(f"   Step 1: CloudScraper fetch...")
            response = self.scraper.get(
                url,
                timeout=10,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            response.raise_for_status()
            logger.info(f"   ✓ CloudScraper status: {response.status_code}")

            # Parse with newspaper4k
            logger.info(f"   Step 2: Newspaper4k extraction...")
            article = Article(url)
            article.download(input_html=response.content)
            article.parse()
            logger.info(f"   ✓ Extraction complete")

            # Compile extraction data
            result = {
                'url': url,
                'title': article.title or 'N/A',
                'authors': article.authors or [],
                'publish_date': str(article.publish_date) if article.publish_date else 'N/A',
                'text_length': len(article.text),
                'text_preview': article.text[:200] + '...' if article.text else 'N/A',
                'extraction_timestamp': datetime.now().isoformat(),
                'success': True
            }

            logger.info(f"   ✓ Title: {result['title'][:60]}...")
            logger.info(f"   ✓ Length: {result['text_length']} chars")

            self.extracted_articles.append(result)
            return result

        except Exception as e:
            logger.error(f"   ✗ Extraction failed: {e}", exc_info=False)
            result = {
                'url': url,
                'success': False,
                'error': str(e),
                'extraction_timestamp': datetime.now().isoformat()
            }
            self.extracted_articles.append(result)
            return result

    def run_full_test(self, discovery_limit: int = 3, extract_limit: int = 2) -> dict:
        """Run full discovery and extraction test."""
        logger.info("=" * 70)
        logger.info("🧪 KY3 CloudScraper Integration Test")
        logger.info("=" * 70)

        summary = {
            'test_start': datetime.now().isoformat(),
            'discovery': {
                'attempted': True,
                'urls_found': 0,
                'urls': []
            },
            'extraction': {
                'attempted': 0,
                'successful': 0,
                'failed': 0,
                'articles': []
            },
            'errors': []
        }

        # Phase 1: Discovery
        logger.info("\n📍 PHASE 1: URL Discovery")
        logger.info("-" * 70)
        urls = self.discover_urls(limit=discovery_limit)
        summary['discovery']['urls_found'] = len(urls)
        summary['discovery']['urls'] = urls

        if not urls:
            logger.warning("⚠️  No URLs discovered, skipping extraction")
            summary['errors'].append("Discovery returned no URLs")
        else:
            # Phase 2: Extraction
            logger.info("\n📍 PHASE 2: Content Extraction")
            logger.info("-" * 70)
            for url in urls[:extract_limit]:
                result = self.extract_article(url)
                summary['extraction']['attempted'] += 1
                if result and result.get('success'):
                    summary['extraction']['successful'] += 1
                else:
                    summary['extraction']['failed'] += 1
                summary['extraction']['articles'].append(result)

        # Phase 3: Summary
        logger.info("\n📍 PHASE 3: Test Summary")
        logger.info("-" * 70)
        logger.info(f"Discovery:")
        logger.info(f"  URLs found: {summary['discovery']['urls_found']}")
        logger.info(f"Extraction:")
        logger.info(f"  Attempted: {summary['extraction']['attempted']}")
        logger.info(f"  Successful: {summary['extraction']['successful']}")
        logger.info(f"  Failed: {summary['extraction']['failed']}")

        summary['test_end'] = datetime.now().isoformat()
        return summary


def main():
    """Run the test."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Test CloudScraper with ky3.com discovery and extraction'
    )
    parser.add_argument(
        '--discovery-limit',
        type=int,
        default=3,
        help='Number of URLs to discover (default: 3)'
    )
    parser.add_argument(
        '--extract-limit',
        type=int,
        default=2,
        help='Number of URLs to extract (default: 2)'
    )
    parser.add_argument(
        '--json-output',
        type=str,
        help='Output test results to JSON file'
    )

    args = parser.parse_args()

    tester = KY3CloudScraperTester()
    results = tester.run_full_test(
        discovery_limit=args.discovery_limit,
        extract_limit=args.extract_limit
    )

    # Output results
    logger.info("\n" + "=" * 70)
    logger.info("Test Results Summary")
    logger.info("=" * 70)
    logger.info(json.dumps(results, indent=2, default=str))

    if args.json_output:
        with open(args.json_output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"\n✓ Results saved to: {args.json_output}")

    # Exit code based on success
    if results['extraction']['successful'] > 0 or results['discovery']['urls_found'] > 0:
        return 0
    else:
        return 1


if __name__ == '__main__':
    sys.exit(main())
