#!/usr/bin/env python3
"""
Backfill script to apply new wire detection rules to existing articles.

This script connects directly to Cloud SQL and re-runs wire detection on articles
that are currently labeled as "labeled" but may actually be wire service content.

Usage:
    python scripts/backfill_wire_detection_cloudsql.py --dry-run
    python scripts/backfill_wire_detection_cloudsql.py --limit 100
    python scripts/backfill_wire_detection_cloudsql.py --apply
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from google.cloud.sql.connector import Connector
import sqlalchemy
from sqlalchemy import text

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.content_type_detector import ContentTypeDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_cloud_sql_engine():
    """Create SQLAlchemy engine using Cloud SQL Python Connector."""
    instance_connection_name = os.environ.get(
        "CLOUD_SQL_INSTANCE",
        "mizzou-news-crawler:us-central1:mizzou-db-prod"
    )
    db_user = os.environ.get("DATABASE_USER", "mizzou_user")
    db_pass = os.environ.get("DATABASE_PASSWORD")
    db_name = os.environ.get("DATABASE_NAME", "mizzou")
    
    if not db_pass:
        raise ValueError(
            "DATABASE_PASSWORD environment variable must be set. "
            "Get it from: kubectl get secret cloudsql-db-credentials -n production "
            "-o jsonpath='{.data.password}' | base64 -d"
        )
    
    logger.info(f"Connecting to Cloud SQL instance: {instance_connection_name}")
    logger.info(f"Database: {db_name}, User: {db_user}")
    
    connector = Connector()
    
    def getconn():
        conn = connector.connect(
            instance_connection_name,
            "pg8000",
            user=db_user,
            password=db_pass,
            db=db_name
        )
        return conn
    
    engine = sqlalchemy.create_engine(
        "postgresql+pg8000://",
        creator=getconn,
    )
    
    return engine, connector


def get_candidates_for_backfill(session, limit: int = None) -> list[tuple]:
    """
    Get articles currently labeled as 'labeled' that might be wire content.

    Returns tuples of (id, url, title, content, author)
    """
    query = text("""
        SELECT
            a.id,
            a.url,
            a.title,
            a.content,
            a.author
        FROM articles a
        WHERE a.status = 'labeled'
        AND a.content IS NOT NULL
        AND a.content != ''
        ORDER BY a.publish_date DESC
    """)
    
    if limit:
        query = text(str(query) + f" LIMIT {limit}")
    
    result = session.execute(query)
    return result.fetchall()


def detect_wire_for_article(
    article_id: int,
    url: str,
    title: str,
    content: str,
    author: str,
    metadata: dict | None = None,
) -> tuple[bool, dict]:
    """
    Run wire detection on an article.

    Returns (is_wire, detection_result_dict)
    """
    detector = ContentTypeDetector()
    
    # Run detection
    # Ensure we pass metadata if provided (contains byline/author info)
    result = detector.detect(
        url=url,
        title=title,
        metadata=metadata,
        content=content,
    )
    
    # Check if detected as wire
    if result and result.status == "wire":
        is_wire = True
        detection_info = {
            "status": result.status,
            "confidence": result.confidence,
            "evidence": result.evidence
        }
    else:
        is_wire = False
        detection_info = {
            "status": result.status if result else "none",
            "confidence": result.confidence if result else 0.0,
            "evidence": result.evidence if result else "No wire service detected"
        }
    
    return is_wire, detection_info


def apply_wire_label(session, article_id: int, evidence: str, dry_run: bool = True):
    """
    Update articles to set status='wire' for the given article.
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would update article {article_id} to status='wire'")
        return
    
    update_query = text("""
        UPDATE articles
        SET
            status = 'wire',
            updated_at = :updated_at
        WHERE id = :article_id
    """)
    
    session.execute(update_query, {
        "article_id": article_id,
        "updated_at": datetime.utcnow()
    })
    session.commit()
    logger.info(f"Updated article {article_id} to status='wire'")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill wire detection for existing articles"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the changes to the database",
    )
    parser.add_argument(
        "--with-byline",
        action="store_true",
        help="Include author byline in detection metadata (default: False)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of articles to process"
    )
    
    args = parser.parse_args()
    
    # Default to dry-run unless --apply is specified
    dry_run = not args.apply
    include_byline = args.with_byline
    
    if dry_run:
        logger.info("=" * 80)
        logger.info("DRY RUN MODE - No changes will be made to the database")
        logger.info("=" * 80)
    else:
        logger.warning("=" * 80)
        logger.warning("APPLY MODE - Changes WILL be made to the database")
        logger.warning("=" * 80)
    
    # Connect to Cloud SQL
    try:
        engine, connector = get_cloud_sql_engine()
    except ValueError as e:
        logger.error(str(e))
        return 1
    
    try:
        with engine.connect() as connection:
            # Test connection
            result = connection.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            logger.info(f"Connected to PostgreSQL: {version[:50]}...")
            
            # Get candidates
            logger.info("Fetching articles labeled as 'labeled'...")
            candidates = get_candidates_for_backfill(connection, limit=args.limit)
            logger.info(f"Found {len(candidates)} articles to check")
            
            # Track results
            wire_detected = []
            not_wire = []
            
            # Process each candidate
            for idx, (article_id, url, title, content, author) in enumerate(
                candidates, 1
            ):
                if idx % 100 == 0:
                    logger.info(f"Processed {idx}/{len(candidates)} articles...")
                
                # Pass byline into metadata when requested so byline-based
                # detections (States Newsroom, WAVE, etc.) are considered
                metadata = {"byline": author} if include_byline and author else None
                is_wire, detection_info = detect_wire_for_article(
                    article_id, url, title, content, author, metadata=metadata
                )
                
                if is_wire:
                    wire_detected.append({
                        "article_id": article_id,
                        "url": url,
                        "title": title,
                        "confidence": detection_info["confidence"],
                        "evidence": detection_info["evidence"]
                    })
                    
                    # Apply label if not dry-run
                    apply_wire_label(
                        connection,
                        article_id,
                        detection_info["evidence"],
                        dry_run=dry_run
                    )
                else:
                    not_wire.append({
                        "article_id": article_id,
                        "title": title
                    })
            
            # Report results
            logger.info("\n" + "=" * 80)
            logger.info("BACKFILL RESULTS")
            logger.info("=" * 80)
            logger.info(f"Total articles checked: {len(candidates)}")
            logger.info(f"Wire service articles detected: {len(wire_detected)}")
            logger.info(f"Local/other articles: {len(not_wire)}")
            
            if wire_detected:
                logger.info("\n" + "-" * 80)
                logger.info("WIRE SERVICE ARTICLES DETECTED:")
                logger.info("-" * 80)
                
                for item in wire_detected:
                    logger.info(f"\nTitle: {item['title'][:100]}...")
                    logger.info(f"URL: {item['url']}")
                    logger.info(f"Confidence: {item['confidence']}")
                    logger.info(f"Evidence: {item['evidence']}")
            
            if dry_run:
                logger.info("\n" + "=" * 80)
                logger.info("DRY RUN COMPLETE - No changes were made")
                logger.info("To apply changes, run with --apply flag")
                logger.info("=" * 80)
            else:
                logger.info("\n" + "=" * 80)
                logger.info("BACKFILL COMPLETE - Changes applied to database")
                logger.info("=" * 80)
    
    except Exception as e:
        logger.error(f"Error during backfill: {e}", exc_info=True)
        return 1
    finally:
        connector.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
