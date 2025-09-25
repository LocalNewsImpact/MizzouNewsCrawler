#!/usr/bin/env python3
"""
StorySniffer dry run analysis for candidate links.
Analyzes which URLs are likely articles vs non-articles.
"""

import sys
import logging
from pathlib import Path
from collections import defaultdict, Counter
from urllib.parse import urlparse
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

# Simple logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_all_candidate_links(db, limit=None):
    """Get all candidate links for analysis."""
    query = "SELECT id, url, source FROM candidate_links WHERE status = 'discovered'"
    if limit:
        query += f" LIMIT {limit}"
    
    with db.engine.connect() as conn:
        result = conn.execute(text(query))
        return [dict(row._mapping) for row in result]


def analyze_url_with_storysniffer(url):
    """Analyze a single URL with StorySniffer."""
    try:
        sniffer = StorySniffer()
        
        # Check if it's likely an article using guess method
        is_article = bool(sniffer.guess(url))
        
        # Get additional classification details
        analysis = {
            'url': url,
            'is_article': is_article,
            'domain': urlparse(url).netloc,
            'path': urlparse(url).path,
            'classification': 'article' if is_article else 'non-article'
        }
        
        return analysis
        
    except Exception as e:
        return {
            'url': url,
            'is_article': None,
            'domain': urlparse(url).netloc,
            'path': urlparse(url).path,
            'classification': 'error',
            'error': str(e)
        }


def categorize_non_articles(non_articles):
    """Categorize non-article URLs by common patterns."""
    categories = defaultdict(list)
    
    for item in non_articles:
        url = item['url'].lower()
        path = item['path'].lower()
        
        # Categorize by common patterns
        if any(pattern in url for pattern in ['/search', '/tag', '/category', '/author']):
            categories['Navigation/Search'].append(item)
        elif any(pattern in url for pattern in ['/video', '/watch', '/podcast']):
            categories['Media Content'].append(item)
        elif any(pattern in url for pattern in ['/contact', '/about', '/privacy', '/terms']):
            categories['Static Pages'].append(item)
        elif any(pattern in url for pattern in ['/rss', '/feed', '.xml']):
            categories['Feeds/XML'].append(item)
        elif any(pattern in url for pattern in ['.jpg', '.png', '.gif', '.pdf', '.css', '.js']):
            categories['File Resources'].append(item)
        elif '/page/' in url or url.endswith('/page'):
            categories['Pagination'].append(item)
        elif len(path.split('/')) <= 2:  # Root or single level paths
            categories['Homepage/Sections'].append(item)
        else:
            categories['Other'].append(item)
    
    return categories


def main():
    """Main analysis function."""
    if not STORYSNIFFER_AVAILABLE:
        logger.error("StorySniffer is not available. Please install with: pip install storysniffer")
        return 1
    
    logger.info("Starting StorySniffer dry run analysis of candidate links")
    
    db = DatabaseManager()
    
    # Get all candidate links (or limit for testing)
    candidates = get_all_candidate_links(db, limit=None)  # Analyze ALL candidates
    logger.info(f"Analyzing {len(candidates)} candidate links with StorySniffer")
    
    if not candidates:
        logger.info("No candidate links found with 'discovered' status")
        return 0
    
    # Track results
    results = {
        'articles': [],
        'non_articles': [],
        'errors': []
    }
    
    source_stats = defaultdict(lambda: {'total': 0, 'articles': 0, 'non_articles': 0, 'errors': 0})
    
    # Analyze each URL
    for i, candidate in enumerate(candidates, 1):
        if i % 100 == 0:
            logger.info(f"Processed {i}/{len(candidates)} URLs...")
        
        analysis = analyze_url_with_storysniffer(candidate['url'])
        analysis['source'] = candidate['source']
        analysis['candidate_id'] = candidate['id']
        
        # Update source statistics
        source_stats[candidate['source']]['total'] += 1
        
        if analysis['classification'] == 'article':
            results['articles'].append(analysis)
            source_stats[candidate['source']]['articles'] += 1
        elif analysis['classification'] == 'non-article':
            results['non_articles'].append(analysis)
            source_stats[candidate['source']]['non_articles'] += 1
        else:
            results['errors'].append(analysis)
            source_stats[candidate['source']]['errors'] += 1
    
    # Generate analysis report
    total_analyzed = len(candidates)
    article_count = len(results['articles'])
    non_article_count = len(results['non_articles'])
    error_count = len(results['errors'])
    
    logger.info("\n" + "="*60)
    logger.info("STORYSNIFFER DRY RUN ANALYSIS RESULTS")
    logger.info("="*60)
    
    print(f"\nOverall Summary:")
    print(f"  Total URLs analyzed: {total_analyzed}")
    print(f"  Likely articles: {article_count} ({article_count/total_analyzed*100:.1f}%)")
    print(f"  Non-articles: {non_article_count} ({non_article_count/total_analyzed*100:.1f}%)")
    print(f"  Errors: {error_count} ({error_count/total_analyzed*100:.1f}%)")
    
    # Source-by-source breakdown
    print(f"\nSource-by-Source Breakdown:")
    print(f"{'Source':<30} {'Total':<8} {'Articles':<10} {'Non-Articles':<12} {'Article %':<10}")
    print("-" * 75)
    
    for source, stats in sorted(source_stats.items()):
        article_pct = (stats['articles'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"{source:<30} {stats['total']:<8} {stats['articles']:<10} {stats['non_articles']:<12} {article_pct:<10.1f}%")
    
    # Non-article categorization
    if results['non_articles']:
        print(f"\nNon-Article URL Categories:")
        categories = categorize_non_articles(results['non_articles'])
        
        for category, items in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"\n{category}: {len(items)} URLs")
            # Show a few examples
            for item in items[:3]:
                print(f"  - {item['url']}")
            if len(items) > 3:
                print(f"  ... and {len(items) - 3} more")
    
    # Domain analysis
    if results['non_articles']:
        print(f"\nTop Domains with Non-Articles:")
        domain_counts = Counter(item['domain'] for item in results['non_articles'])
        for domain, count in domain_counts.most_common(10):
            print(f"  {domain}: {count} non-articles")
    
    # Error analysis
    if results['errors']:
        print(f"\nError Analysis:")
        error_types = Counter(item.get('error', 'Unknown') for item in results['errors'])
        for error, count in error_types.most_common(5):
            print(f"  {error}: {count} occurrences")
    
    # Save detailed results to file
    output_file = Path(__file__).parent / "storysniffer_analysis_results.txt"
    with open(output_file, 'w') as f:
        f.write("DETAILED STORYSNIFFER ANALYSIS RESULTS\n")
        f.write("="*60 + "\n\n")
        
        f.write("NON-ARTICLE URLs:\n")
        f.write("-" * 30 + "\n")
        for item in results['non_articles']:
            f.write(f"URL: {item['url']}\n")
            f.write(f"Source: {item['source']}\n")
            f.write(f"Domain: {item['domain']}\n")
            f.write(f"Path: {item['path']}\n\n")
        
        f.write("\nARTICLE URLs (Sample):\n")
        f.write("-" * 30 + "\n")
        for item in results['articles'][:50]:  # Show first 50 articles
            f.write(f"URL: {item['url']}\n")
            f.write(f"Source: {item['source']}\n")
            f.write(f"Domain: {item['domain']}\n\n")
    
    logger.info(f"\nDetailed results saved to: {output_file}")
    
    return 0


if __name__ == "__main__":
    exit(main())