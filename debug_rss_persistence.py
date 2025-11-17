#!/usr/bin/env python3
"""Debug script to test RSS persistence logic locally against production database.

This script:
1. Queries production DB for a source with known 403 errors (mymoinfo.com)
2. Simulates the discovery flow with actual SourceProcessor code
3. Checks if _persist_rss_metadata() executes and logs RSS_PERSIST
4. Reveals the actual execution path without needing a full rebuild
"""
import logging
import sys
import pandas as pd

# Enable ALL logging including DEBUG
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    logger.info("=== RSS Persistence Debug Script ===")
    
    # Import after logging setup
    from src.models.database import DatabaseManager
    from src.crawler.discovery import NewsDiscovery
    from src.crawler.source_processing import SourceProcessor
    
    db = DatabaseManager()
    
    # Get mymoinfo.com which has known 403 errors
    logger.info("Fetching mymoinfo.com source from production...")
    with db.get_session() as session:
        from sqlalchemy import text
        result = session.execute(text("""
            SELECT id, canonical_name, 'https://' || host as url, host,
                   rss_consecutive_failures, rss_transient_failures,
                   rss_missing_at, rss_last_failed_at, metadata
            FROM sources
            WHERE host = 'mymoinfo.com'
            LIMIT 1
        """)).fetchone()
        
        if not result:
            logger.error("mymoinfo.com not found in production database")
            return 1
        
        # Convert to dict for pandas Series
        source_data = {
            'id': result[0],
            'canonical_name': result[1],
            'name': result[1],  # Alias for compatibility
            'url': result[2],
            'host': result[3],
            'rss_consecutive_failures': result[4],
            'rss_transient_failures': result[5],
            'rss_missing_at': result[6],
            'rss_last_failed_at': result[7],
            'metadata': result[8]
        }
        
        logger.info(f"Source: {source_data['name']} (ID: {source_data['id']})")
        logger.info(f"RSS URLs: {source_data['rss_urls']}")
        logger.info(f"RSS consecutive failures: {source_data['rss_consecutive_failures']}")
        logger.info(f"RSS transient failures: {source_data['rss_transient_failures']}")
        logger.info(f"RSS last failed: {source_data['rss_last_failed_at']}")
    
    # Create NewsDiscovery instance
    logger.info("\n=== Creating NewsDiscovery instance ===")
    discovery = NewsDiscovery(max_articles_per_source=10, days_back=7)
    
    # Create source row
    logger.info("\n=== Creating SourceProcessor ===")
    source_row = pd.Series(source_data)
    
    # Create SourceProcessor - this is what production does
    processor = SourceProcessor(
        discovery=discovery,
        source_row=source_row,
        dataset_label=None,
        operation_id="debug-test",
        date_parser=None,
    )
    
    logger.info("\n=== Initializing context ===")
    processor._initialize_context()
    
    logger.info(f"source_id after init: {processor.source_id}")
    logger.info(f"effective_methods: {processor.effective_methods}")
    
    # Check if RSS_FEED is in effective methods
    from src.utils.telemetry import DiscoveryMethod
    if DiscoveryMethod.RSS_FEED not in processor.effective_methods:
        logger.warning("⚠️  RSS_FEED not in effective_methods! This explains why _try_rss() isn't called!")
        logger.warning(f"Effective methods: {processor.effective_methods}")
        return 1
    
    logger.info("\n=== Calling _try_rss() directly ===")
    try:
        result = processor._try_rss()
        logger.info(f"_try_rss() returned: {result}")
        logger.info(f"Articles found: {len(result) if result else 0}")
    except Exception:
        logger.exception("_try_rss() raised exception")
        return 1
    
    logger.info("\n=== SUCCESS - Check logs above for RSS_PERSIST message ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
