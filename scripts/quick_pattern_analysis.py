#!/usr/bin/env python3
"""
Quick StorySniffer pattern analysis for specific URL types.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager

try:
    from storysniffer import StorySniffer
    STORYSNIFFER_AVAILABLE = True
except ImportError:
    STORYSNIFFER_AVAILABLE = False
    StorySniffer = None


def analyze_specific_patterns():
    """Analyze specific URL patterns that might be problematic."""
    if not STORYSNIFFER_AVAILABLE:
        print("StorySniffer not available")
        return

    db = DatabaseManager()
    sniffer = StorySniffer()

    # Define patterns to test
    patterns = {
        'calendars': '/calendar',
        'obituaries': '/obituary',
        'categories': '/category/',
        'tags': '/tag/',
        'search': '/search',
        'contact': '/contact',
        'about': '/about',
        'css_files': '.css',
        'image_files': '.jpg',
        'feeds': '/feed',
        'rss': '/rss'
    }

    print("URL Pattern Analysis with StorySniffer")
    print("=" * 50)

    for pattern_name, pattern in patterns.items():
        print(f"\nAnalyzing URLs containing '{pattern}':")

        with db.engine.connect() as conn:
            result = conn.execute(text(
                "SELECT url FROM candidate_links WHERE status = 'discovered' AND url LIKE :pattern LIMIT 10"
            ), {'pattern': f'%{pattern}%'})
            urls = [row[0] for row in result]

        if not urls:
            print(f"  No URLs found with pattern '{pattern}'")
            continue

        article_count = 0
        non_article_count = 0

        print(f"  Found {len(urls)} URLs, analyzing...")

        for url in urls:
            try:
                is_article = bool(sniffer.guess(url))
                if is_article:
                    article_count += 1
                else:
                    non_article_count += 1
                    print(f"    NON-ARTICLE: {url}")
            except Exception as e:
                print(f"    ERROR: {url} - {e}")

        if len(urls) > 0:
            non_article_pct = (non_article_count / len(urls)) * 100
            print(f"  Results: {non_article_count}/{len(urls)} ({non_article_pct:.1f}%) identified as non-articles")


if __name__ == "__main__":
    analyze_specific_patterns()
