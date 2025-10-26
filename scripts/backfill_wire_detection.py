#!/usr/bin/env python3
"""
Backfill script to apply new wire detection rules to existing articles.

This script re-runs wire detection on articles that are currently labeled as "labeled"
but may actually be wire service content based on the new dateline-based detection.

Usage:
    python scripts/backfill_wire_detection.py --dry-run
    python scripts/backfill_wire_detection.py --limit 100
    python scripts/backfill_wire_detection.py --apply
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
        INNER JOIN article_labels al ON a.id = al.article_id
        WHERE al.status = 'labeled'
        AND a.content IS NOT NULL
        AND a.content != ''
        ORDER BY a.publish_date DESC
    """)
    
    if limit:
        query = text(str(query) + f" LIMIT {limit}")
    
    result = session.execute(query)
    return result.fetchall()


def detect_wire_for_article(article_id: int, url: str, title: str,
                            content: str, author: str) -> tuple[bool, dict]:
    """
    Run wire detection on an article.

    Returns (is_wire, detection_result_dict)
    """
    detector = ContentTypeDetector()
    
    # Run detection
    result = detector.detect(
        url=url,
        headline=title,
        content=content,
        byline=author or ""
    )
    
    # Check if detected as wire
    is_wire = result.status == "wire"
    
    detection_info = {
        "status": result.status,
        "confidence": result.confidence,
        "evidence": result.evidence
    }
    
    return is_wire, detection_info


def apply_wire_label(session, article_id: int, evidence: str, dry_run: bool = True):
    """
    Update article_labels to set status='wire' for the given article.
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would update article {article_id} to status='wire'")
        return
    
    update_query = text("""
        UPDATE article_labels
        SET
            status = 'wire',
            applied_at = :applied_at,
            notes = :notes
        WHERE article_id = :article_id
    """)
    
    session.execute(update_query, {
        "article_id": article_id,
        "applied_at": datetime.utcnow(),
        "notes": f"Backfilled wire detection: {evidence}"
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
        help="Actually apply the changes to the database"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of articles to process"
    )
    
    args = parser.parse_args()
    
    # Default to dry-run unless --apply is specified
    dry_run = not args.apply
    
    if dry_run:
        logger.info("=" * 80)
        logger.info("DRY RUN MODE - No changes will be made to the database")
        logger.info("=" * 80)
    else:
        logger.warning("=" * 80)
        logger.warning("APPLY MODE - Changes WILL be made to the database")
        logger.warning("=" * 80)
    
    # Connect to database
    db = DatabaseManager()
    
    with db.get_session() as session:
        try:
            # Get candidates
            logger.info("Fetching articles labeled as 'labeled'...")
            candidates = get_candidates_for_backfill(session, limit=args.limit)
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
                
                is_wire, detection_info = detect_wire_for_article(
                    article_id, url, title, content, author
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
                        session,
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
            session.rollback()
            raise


if __name__ == "__main__":
    main()
