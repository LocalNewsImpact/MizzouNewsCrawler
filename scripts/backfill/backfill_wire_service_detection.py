#!/usr/bin/env python3
"""
Backfill wire service detection for articles that were extracted before 
wire service detection was implemented.

This script:
1. Finds articles with status="extracted" that have author information
2. Re-runs the byline cleaner with wire service detection
3. Updates articles to status="wire" and populates wire column when appropriate
"""

import json
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from sqlalchemy import text

from models.database import DatabaseManager
from utils.byline_cleaner import BylineCleaner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("wire_backfill.log"),
    ],
)

logger = logging.getLogger(__name__)


def backfill_wire_service_detection(dry_run=True, limit=None):
    """
    Backfill wire service detection for extracted articles.
    
    Args:
        dry_run: If True, only report what would be changed without making changes
        limit: Optional limit on number of articles to process
    """
    db = DatabaseManager()
    session = db.session
    # Disable telemetry to avoid database lock conflicts during backfill
    byline_cleaner = BylineCleaner(enable_telemetry=False)

    try:
        # Find articles with status="extracted" that have author information
        query = """
        SELECT id, author, url, candidate_link_id 
        FROM articles 
        WHERE status = 'extracted' 
        AND author IS NOT NULL 
        AND author != '[]'
        AND author != ''
        ORDER BY created_at DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        result = session.execute(text(query))
        articles = result.fetchall()

        logger.info(f"Found {len(articles)} extracted articles with author information")

        if not articles:
            logger.info("No articles to backfill")
            return

        wire_detected_count = 0
        processed_count = 0

        for article in articles:
            article_id, author_json, url, candidate_link_id = article

            try:
                # Parse the author JSON
                if author_json and author_json.strip():
                    # Handle both JSON array format and plain string
                    if author_json.startswith('['):
                        authors = json.loads(author_json)
                        if authors:
                            raw_author = authors[0]  # Use first author for detection
                        else:
                            continue
                    else:
                        raw_author = author_json

                    # Re-run byline cleaner with wire service detection
                    byline_result = byline_cleaner.clean_byline(
                        raw_author,
                        return_json=True,
                        candidate_link_id=str(candidate_link_id)
                    )

                    # Check if wire services were detected
                    wire_services = byline_result.get("wire_services", [])
                    is_wire_content = byline_result.get("is_wire_content", False)
                    cleaned_authors = byline_result.get("authors", [])

                    if is_wire_content and wire_services:
                        wire_detected_count += 1

                        logger.info(
                            f"Wire service detected for article {article_id}: "
                            f"'{raw_author}' → Wire services: {wire_services}"
                        )

                        if not dry_run:
                            # Update the article status and wire column
                            session.execute(
                                text(
                                    "UPDATE articles SET status = :status, wire = :wire, "
                                    "author = :author WHERE id = :id"
                                ),
                                {
                                    "status": "wire",
                                    "wire": json.dumps(wire_services),
                                    "author": json.dumps(cleaned_authors),
                                    "id": article_id,
                                },
                            )

                            # Also update the candidate_links status
                            if candidate_link_id:
                                session.execute(
                                    text(
                                        "UPDATE candidate_links SET status = :status "
                                        "WHERE id = :id"
                                    ),
                                    {"status": "wire", "id": str(candidate_link_id)},
                                )

                    processed_count += 1

                    if processed_count % 100 == 0:
                        logger.info(f"Processed {processed_count} articles...")

            except Exception as e:
                logger.error(f"Error processing article {article_id}: {e}")
                continue

        if not dry_run:
            session.commit()
            logger.info("Changes committed to database")
        else:
            logger.info("DRY RUN - No changes made to database")

        logger.info(
            f"Backfill complete. Processed: {processed_count}, "
            f"Wire services detected: {wire_detected_count}"
        )

        # Show summary of what would be changed
        if dry_run and wire_detected_count > 0:
            logger.info(
                f"\nDRY RUN SUMMARY: {wire_detected_count} articles would be "
                f"updated from status='extracted' to status='wire'"
            )

        return {
            "processed": processed_count,
            "wire_detected": wire_detected_count,
            "dry_run": dry_run
        }

    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def main():
    """Main function with CLI arguments."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill wire service detection for extracted articles"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Only show what would be changed (default: True)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the backfill (overrides --dry-run)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of articles to process"
    )

    args = parser.parse_args()

    # If --execute is specified, turn off dry_run
    dry_run = not args.execute

    logger.info(f"Starting wire service backfill (dry_run={dry_run})")

    result = backfill_wire_service_detection(
        dry_run=dry_run,
        limit=args.limit
    )

    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
