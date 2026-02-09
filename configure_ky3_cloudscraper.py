#!/usr/bin/env python3
"""Configure ky3.com to use CloudScraper for extraction."""

import sys
import logging
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def configure_ky3_extraction():
    """Configure ky3.com sources to use CloudScraper (HTTP method)."""
    try:
        from src.models.database import DatabaseManager

        db = DatabaseManager()
        
        with db.get_session() as session:
            # Find ky3 sources
            logger.info("🔍 Finding ky3.com sources...")
            query = text("""
                SELECT id, host, canonical_name, extraction_method, bot_protection_type
                FROM sources
                WHERE host LIKE '%ky3.com%'
                   OR canonical_name LIKE '%KY3%'
                   OR canonical_name LIKE '%KSPR%'
            """)
            
            results = session.execute(query).fetchall()
            
            if not results:
                logger.warning("⚠️  No KY3 sources found in database")
                return 1
            
            logger.info(f"Found {len(results)} KY3 source(s):")
            for row in results:
                logger.info(f"  ID: {row[0]}")
                logger.info(f"    Host: {row[1]}")
                logger.info(f"    Name: {row[2]}")
                logger.info(f"    Current extraction_method: {row[3]}")
                logger.info(f"    Bot protection type: {row[4]}")
            
            # Update to use HTTP method (CloudScraper will handle Cloudflare automatically)
            # Keep bot_protection_type='cloudflare' so system knows about the protection
            logger.info("\n📝 Updating extraction configuration...")
            update_query = text("""
                UPDATE sources
                SET extraction_method = 'http'
                WHERE host LIKE '%ky3.com%'
                   OR canonical_name LIKE '%KY3%'
                   OR canonical_name LIKE '%KSPR%'
            """)
            
            session.execute(update_query)
            session.commit()
            
            logger.info("✅ Updated extraction_method to 'http' for KY3 sources")
            logger.info("   CloudScraper will be used automatically for requests")
            
            # Verify the update
            verify_query = text("""
                SELECT id, host, canonical_name, extraction_method, bot_protection_type
                FROM sources
                WHERE host LIKE '%ky3.com%'
                   OR canonical_name LIKE '%KY3%'
                   OR canonical_name LIKE '%KSPR%'
            """)
            
            updated_results = session.execute(verify_query).fetchall()
            logger.info("\n✓ Updated sources:")
            for row in updated_results:
                logger.info(f"  {row[2]} ({row[1]})")
                logger.info(f"    extraction_method: {row[3]}")
                logger.info(f"    bot_protection_type: {row[4]}")
            
            return 0

    except Exception as e:
        logger.error(f"✗ Configuration failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(configure_ky3_extraction())
