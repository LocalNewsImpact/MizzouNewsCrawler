"""Content cleaning command for processing extracted articles."""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from urllib.parse import urlparse

from sqlalchemy import text

from src.models.database import DatabaseManager, calculate_content_hash
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner

logger = logging.getLogger(__name__)

ARTICLE_UPDATE_SQL = text("""
    UPDATE articles
    SET content = :content,
        text = :text,
        text_hash = :text_hash,
        text_excerpt = :excerpt,
        status = :status
    WHERE id = :id
""")


def add_cleaning_parser(subparsers) -> argparse.ArgumentParser:
    """Add content cleaning command parser to CLI."""
    clean_parser = subparsers.add_parser(
        "clean-articles",
        help="Clean content and update status for extracted articles",
    )
    clean_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of articles to clean per run (default: 50)",
    )
    clean_parser.add_argument(
        "--status",
        action="append",
        default=None,
        help=(
            "Article status to clean (default: extracted). "
            "Can be specified multiple times"
        ),
    )

    clean_parser.set_defaults(func=handle_cleaning_command)
    return clean_parser


def handle_cleaning_command(args) -> int:
    """Execute content cleaning command logic."""
    limit = getattr(args, "limit", 50)
    statuses = getattr(args, "status", None) or ["extracted"]

    logger.info("Starting content cleaning: limit=%d, statuses=%s", limit, statuses)
    print("🧹 Starting content cleaning...")
    print(f"   Limit: {limit} articles")
    print(f"   Statuses: {', '.join(statuses)}")
    print()

    cleaner = BalancedBoundaryContentCleaner(enable_telemetry=True)
    db = DatabaseManager()

    processed = 0
    cleaned = 0
    errors = 0
    status_changes = defaultdict(int)

    try:
        with db.get_session() as session:
            # Get articles needing cleaning
            status_placeholders = ", ".join(
                [f":status{i}" for i in range(len(statuses))]
            )
            query = text(f"""
                SELECT a.id, a.content, a.status, cl.url
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE a.status IN ({status_placeholders})
                AND a.content IS NOT NULL
                AND a.content != ''
                LIMIT :limit
            """)

            params = {"limit": limit}
            for i, status in enumerate(statuses):
                params[f"status{i}"] = status

            result = session.execute(query, params)
            articles = result.fetchall()

            if not articles:
                print("📭 No articles found needing cleaning")
                return 0

            print(f"📊 Found {len(articles)} articles to clean")
            print()

            # Group by domain
            articles_by_domain = defaultdict(list)
            for article_id, content, status, url in articles:
                domain = urlparse(url).netloc
                articles_by_domain[domain].append((article_id, content, status))

            # Process each domain
            for domain, domain_articles in articles_by_domain.items():
                # NOTE: We don't call analyze_domain() because it tries to query
                # the database with SQLite. Instead, process_single_article() will
                # handle cleaning using the content we already have.
                
                for article_id, original_content, current_status in domain_articles:
                    try:
                        cleaned_content, metadata = cleaner.process_single_article(
                            text=original_content,
                            domain=domain,
                            article_id=article_id,
                        )

                        wire_detected = metadata.get("wire_detected")
                        locality_assessment = metadata.get("locality_assessment") or {}
                        is_local_wire = bool(
                            wire_detected
                            and locality_assessment
                            and locality_assessment.get("is_local")
                        )

                        # Determine new status
                        new_status = current_status
                        if is_local_wire:
                            if current_status in {"wire", "cleaned", "extracted"}:
                                new_status = "local"
                        elif wire_detected:
                            if current_status == "extracted":
                                new_status = "wire"
                        elif current_status == "extracted":
                            new_status = "cleaned"

                        # Determine if we need to update the article
                        content_changed = cleaned_content != original_content
                        status_changed = new_status != current_status
                        
                        # Update if content changed OR status changed
                        if content_changed or status_changed:
                            new_hash = (
                                calculate_content_hash(cleaned_content)
                                if cleaned_content
                                else None
                            )
                            excerpt = cleaned_content[:500] if cleaned_content else None

                            session.execute(
                                ARTICLE_UPDATE_SQL,
                                {
                                    "content": cleaned_content,
                                    "text": cleaned_content,
                                    "text_hash": new_hash,
                                    "excerpt": excerpt,
                                    "status": new_status,
                                    "id": article_id,
                                },
                            )

                            chars_removed = metadata.get("chars_removed", 0)
                            logger.info(
                                f"Cleaned article {article_id[:8]}... "
                                f"({domain}): removed {chars_removed} chars, "
                                f"status {current_status} → {new_status}"
                            )

                            if content_changed:
                                cleaned += 1
                            if status_changed:
                                status_changes[f"{current_status}→{new_status}"] += 1

                        processed += 1

                        # Commit every 10 articles
                        if processed % 10 == 0:
                            session.commit()
                            print(
                                f"✓ Progress: {processed}/{len(articles)} "
                                f"articles processed"
                            )

                    except Exception:
                        logger.exception(f"Error cleaning article {article_id}")
                        errors += 1

            # Final commit
            session.commit()

        print()
        print("✅ Content cleaning completed!")
        print(f"   Articles processed: {processed}")
        print(f"   Content cleaned: {cleaned}")
        print(f"   Errors: {errors}")

        if status_changes:
            print()
            print("   Status changes:")
            for change, count in sorted(status_changes.items()):
                print(f"     {change}: {count} articles")

        return 0

    except Exception:
        logger.exception("Content cleaning failed")
        return 1


if __name__ == "__main__":
    # For testing
    import sys

    logging.basicConfig(level=logging.INFO)
    args = argparse.Namespace(limit=10, status=["extracted"])
    sys.exit(handle_cleaning_command(args))
