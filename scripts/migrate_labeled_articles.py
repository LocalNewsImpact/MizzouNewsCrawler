#!/usr/bin/env python3
"""Migration script to update articles with labels to status='labeled'.

This fixes articles that were classified but not marked as 'labeled' before
the fix in commit f9c799e. These articles have primary_label set but are
stuck in status='cleaned' or 'local', preventing them from being exported
to BigQuery.

Usage:
    python scripts/migrate_labeled_articles.py [--dry-run] [--limit N]
"""

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import text

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.database import DatabaseManager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_labeled_articles(dry_run: bool = False, limit: int | None = None) -> dict:
    """Update articles with labels to status='labeled'.
    
    Args:
        dry_run: If True, only count articles without making changes
        limit: Maximum number of articles to update (for testing)
    
    Returns:
        Dictionary with migration statistics
    """
    stats = {
        'cleaned_to_labeled': 0,
        'local_to_labeled': 0,
        'total_updated': 0,
        'already_labeled': 0,
    }
    
    with DatabaseManager() as db:
        # First, count what we have
        logger.info("Analyzing articles with labels...")
        
        # Count articles with labels by status
        result = db.session.execute(text("""
            SELECT status, COUNT(*) as count
            FROM articles
            WHERE primary_label IS NOT NULL
            GROUP BY status
            ORDER BY count DESC
        """))
        
        logger.info("Articles with primary_label by status:")
        for row in result:
            logger.info(f"  {row[0]}: {row[1]} articles")
            if row[0] == 'labeled':
                stats['already_labeled'] = row[1]
        
        # Find articles that need migration
        if limit:
            limit_clause = f"LIMIT {limit}"
        else:
            limit_clause = ""
        
        result = db.session.execute(text(f"""
            SELECT id, url, status, primary_label, extracted_at
            FROM articles
            WHERE primary_label IS NOT NULL
            AND status IN ('cleaned', 'local')
            ORDER BY extracted_at DESC
            {limit_clause}
        """))
        
        articles_to_update = result.fetchall()
        
        if not articles_to_update:
            logger.info(
                "✅ No articles need migration - "
                "all labeled articles already have status='labeled'"
            )
            return stats
        
        logger.info(f"\n📊 Found {len(articles_to_update)} articles to migrate:")
        
        # Count by current status
        from collections import Counter
        status_counts = Counter(row[2] for row in articles_to_update)
        for status, count in status_counts.items():
            logger.info(f"  {status}: {count} articles")
        
        if dry_run:
            logger.info("\n🔍 DRY RUN - No changes will be made")
            logger.info(
                f"Would update {len(articles_to_update)} articles "
                "to status='labeled'"
            )
            
            # Show a few examples
            logger.info("\nExample articles that would be updated:")
            for row in articles_to_update[:5]:
                article_id, url, status, label, extracted_at = row
                logger.info(f"  [{status}→labeled] {label}: {url[:80]}")
            
            stats['total_updated'] = len(articles_to_update)
            stats['cleaned_to_labeled'] = status_counts.get('cleaned', 0)
            stats['local_to_labeled'] = status_counts.get('local', 0)
            return stats
        
        # Perform the migration
        logger.info(
            f"\n🔄 Updating {len(articles_to_update)} articles "
            "to status='labeled'..."
        )
        
        result = db.session.execute(text("""
            UPDATE articles
            SET status = 'labeled'
            WHERE primary_label IS NOT NULL
            AND status IN ('cleaned', 'local')
        """))
        
        db.session.commit()
        
        updated_count = len(articles_to_update)
        stats['total_updated'] = updated_count
        stats['cleaned_to_labeled'] = status_counts.get('cleaned', 0)
        stats['local_to_labeled'] = status_counts.get('local', 0)
        
        logger.info(
            f"✅ Successfully updated {updated_count} articles "
            "to status='labeled'"
        )
        
        # Verify the migration
        result = db.session.execute(text("""
            SELECT COUNT(*)
            FROM articles
            WHERE primary_label IS NOT NULL
            AND status = 'labeled'
        """))
        
        total_labeled = result.scalar()
        logger.info(f"\n📊 Total articles with status='labeled': {total_labeled}")
        
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Migrate classified articles to status='labeled'"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of articles to update (for testing)'
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("Article Status Migration")
    logger.info("=" * 80)
    
    try:
        stats = migrate_labeled_articles(
            dry_run=args.dry_run,
            limit=args.limit
        )
        
        logger.info("\n" + "=" * 80)
        logger.info("Migration Summary:")
        logger.info("=" * 80)
        logger.info(
            f"Articles updated 'cleaned' → 'labeled': "
            f"{stats['cleaned_to_labeled']}"
        )
        logger.info(
            f"Articles updated 'local' → 'labeled': "
            f"{stats['local_to_labeled']}"
        )
        logger.info(f"Total articles updated: {stats['total_updated']}")
        logger.info(f"Articles already labeled: {stats['already_labeled']}")
        logger.info("=" * 80)
        
        if args.dry_run:
            logger.info("\n💡 Run without --dry-run to apply the migration")
            return 0
        else:
            logger.info(
                "\n✅ Migration complete! "
                "Classified articles are now marked as 'labeled'"
            )
            logger.info(
                "   These articles will be included in the "
                "next BigQuery export."
            )
            return 0
            
    except Exception as e:
        logger.exception(f"❌ Migration failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
