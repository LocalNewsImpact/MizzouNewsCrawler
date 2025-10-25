#!/usr/bin/env python3
"""
Fix duplicate articles and add unique constraint on URL.

This script safely deduplicates articles by URL, keeping the most recent
extraction for each URL. It is idempotent and safe to re-run.

IMPORTANT:
- Stop all extraction jobs before running this script
- This script is designed to run BEFORE the migration
- For production use, consider taking a database backup first

The script performs:
1. Analysis of duplicate articles
2. Archive of duplicates to be removed (optional)
3. Deletion of child records for duplicate articles
4. Deletion of duplicate articles (keeping most recent by extracted_at)
5. Verification of cleanup
6. Index creation (optional - usually done via migration)
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from sqlalchemy import text

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def analyze_duplicates(conn):
    """Analyze and report on duplicate articles.

    Returns:
        dict with keys:
            - duplicate_urls: number of URLs with duplicates
            - total_duplicate_articles: total number of duplicate article records
            - examples: list of (url, count) tuples showing worst duplicates
    """
    logger.info("Analyzing duplicate articles...")

    # Find URLs with duplicates
    result = conn.execute(
        text(
            """
        SELECT url, COUNT(*) as count
        FROM articles
        GROUP BY url
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 10
    """
        )
    )

    examples = [(row[0], row[1]) for row in result.fetchall()]

    if not examples:
        logger.info("✓ No duplicate URLs found")
        return {"duplicate_urls": 0, "total_duplicate_articles": 0, "examples": []}

    # Count total duplicate articles (not kept)
    result = conn.execute(
        text(
            """
        SELECT COUNT(*) FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
            FROM articles
        ) t WHERE t.rn > 1
    """
        )
    )
    total_duplicates = result.scalar() or 0

    logger.info(f"Found {len(examples)} URLs with duplicates")
    logger.info(f"Total duplicate article records to remove: {total_duplicates}")
    logger.info("Top duplicate URLs:")
    for url, count in examples[:5]:
        logger.info(f"  - {url}: {count} copies")

    return {
        "duplicate_urls": len(examples),
        "total_duplicate_articles": total_duplicates,
        "examples": examples,
    }


def clean_duplicates(dry_run=False, create_index=False):
    """Delete duplicate articles, keeping most recent.

    Args:
        dry_run: If True, only analyze without making changes
        create_index: If True, create unique index after cleanup
    """
    db = DatabaseManager()
    is_postgresql = "postgresql" in db.database_url.lower()

    # Use AUTOCOMMIT for PostgreSQL DDL, regular transaction for DML
    if dry_run:
        conn = db.engine.connect()
    else:
        # For actual deletion, use AUTOCOMMIT to avoid transaction timeout
        conn = db.engine.connect().execution_options(isolation_level="AUTOCOMMIT")

    try:
        # Step 0: Analyze duplicates
        analysis = analyze_duplicates(conn)

        if analysis["total_duplicate_articles"] == 0:
            logger.info("✓ No duplicates to clean up")
            if create_index:
                logger.info("Proceeding to create unique index...")
            else:
                return

        if dry_run:
            logger.info("\n=== DRY RUN MODE - No changes will be made ===")
            logger.info(
                f"Would delete {analysis['total_duplicate_articles']} duplicate articles"
            )
            return

        # Confirm before proceeding
        logger.warning("\n⚠️  ABOUT TO DELETE DUPLICATE ARTICLES")
        logger.warning(
            f"   This will remove {analysis['total_duplicate_articles']} article records"
        )
        logger.warning("   Keeping the most recent extraction for each URL")
        response = input("\nProceed with deletion? (yes/no): ")
        if response.lower() not in ("yes", "y"):
            logger.info("Aborted by user")
            return

        logger.info("\nStep 1: Deleting child records for duplicates...")

        # Delete article_labels
        if is_postgresql:
            result = conn.execute(
                text(
                    """
                DELETE FROM article_labels
                WHERE article_id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                        FROM articles
                    ) t WHERE t.rn > 1
                )
            """
                )
            )
        else:
            # SQLite doesn't support DELETE with window functions in subquery
            # Use a two-step approach
            result = conn.execute(
                text(
                    """
                DELETE FROM article_labels
                WHERE article_id IN (
                    SELECT a.id FROM articles a
                    WHERE EXISTS (
                        SELECT 1 FROM articles a2
                        WHERE a2.url = a.url
                        AND a2.extracted_at > a.extracted_at
                    )
                )
            """
                )
            )
        logger.info(f"  Deleted {result.rowcount} article_labels")

        # Delete article_entities
        if is_postgresql:
            result = conn.execute(
                text(
                    """
                DELETE FROM article_entities  
                WHERE article_id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                        FROM articles
                    ) t WHERE t.rn > 1
                )
            """
                )
            )
        else:
            result = conn.execute(
                text(
                    """
                DELETE FROM article_entities
                WHERE article_id IN (
                    SELECT a.id FROM articles a
                    WHERE EXISTS (
                        SELECT 1 FROM articles a2
                        WHERE a2.url = a.url
                        AND a2.extracted_at > a.extracted_at
                    )
                )
            """
                )
            )
        logger.info(f"  Deleted {result.rowcount} article_entities")

        # Delete ml_results
        if is_postgresql:
            result = conn.execute(
                text(
                    """
                DELETE FROM ml_results
                WHERE article_id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                        FROM articles
                    ) t WHERE t.rn > 1
                )
            """
                )
            )
        else:
            result = conn.execute(
                text(
                    """
                DELETE FROM ml_results
                WHERE article_id IN (
                    SELECT a.id FROM articles a
                    WHERE EXISTS (
                        SELECT 1 FROM articles a2
                        WHERE a2.url = a.url
                        AND a2.extracted_at > a.extracted_at
                    )
                )
            """
                )
            )
        logger.info(f"  Deleted {result.rowcount} ml_results")

        logger.info("\nStep 2: Deleting duplicate articles (keeping most recent)...")
        if is_postgresql:
            result = conn.execute(
                text(
                    """
                DELETE FROM articles
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                        FROM articles
                    ) t WHERE t.rn > 1
                )
            """
                )
            )
        else:
            result = conn.execute(
                text(
                    """
                DELETE FROM articles
                WHERE id IN (
                    SELECT a.id FROM articles a
                    WHERE EXISTS (
                        SELECT 1 FROM articles a2
                        WHERE a2.url = a.url
                        AND a2.extracted_at > a.extracted_at
                    )
                )
            """
                )
            )
        deleted_count = result.rowcount
        logger.info(f"  Deleted {deleted_count} duplicate articles")

        # Verify cleanup
        logger.info("\nStep 3: Verifying cleanup...")
        verification = analyze_duplicates(conn)
        if verification["total_duplicate_articles"] > 0:
            logger.error(
                f"⚠️  Cleanup incomplete: {verification['total_duplicate_articles']} duplicates remain"
            )
            logger.error("This may indicate a problem with the cleanup logic")
        else:
            logger.info("  ✓ All duplicates removed successfully")

        if create_index:
            logger.info("\nStep 4: Adding unique constraint...")
            if is_postgresql:
                # Use CONCURRENTLY for production safety
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_articles_url ON articles (url)"
                    )
                )
            else:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_url ON articles (url)"
                    )
                )
            logger.info("  ✓ Unique constraint added!")

        logger.info("\n✅ Deduplication complete!")
        logger.info(f"   Removed {deleted_count} duplicate article records")
        logger.info("   Extraction can now safely use ON CONFLICT DO NOTHING")

    except Exception as e:
        logger.error(f"Error during deduplication: {e}", exc_info=True)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Remove duplicate articles from the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze duplicates without making changes
  python scripts/fix_article_duplicates.py --dry-run
  
  # Remove duplicates (with confirmation prompt)
  python scripts/fix_article_duplicates.py
  
  # Remove duplicates and create unique index
  python scripts/fix_article_duplicates.py --create-index
  
  # Skip confirmation prompt (use with caution)
  python scripts/fix_article_duplicates.py --yes
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze duplicates without making changes",
    )
    parser.add_argument(
        "--create-index",
        action="store_true",
        help="Create unique index after cleanup (usually done via migration)",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )

    args = parser.parse_args()

    # Override confirmation if --yes flag provided
    if args.yes and not args.dry_run:
        # Monkeypatch input to auto-confirm
        import builtins

        builtins.input = lambda _: "yes"

    clean_duplicates(dry_run=args.dry_run, create_index=args.create_index)
