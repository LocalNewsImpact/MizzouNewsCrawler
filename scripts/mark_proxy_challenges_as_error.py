#!/usr/bin/env python3
"""
Mark existing articles with proxy/bot challenge titles as error status
to prevent them from being exported to BigQuery.

Usage:
    kubectl exec -n production deployment/mizzou-api -- python scripts/mark_proxy_challenges_as_error.py
"""

import logging

from sqlalchemy import text

from src.models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Proxy/bot challenge patterns to detect
PROXY_PATTERNS = [
    "Access to this page has been denied",
    "Attention Required",
    "Just a moment",
    "Please verify you are a human",
    "Checking your browser",
    "Access Denied",
]


def mark_proxy_challenges_as_error():
    """Find and mark articles with proxy challenge titles/content as error status."""
    db = DatabaseManager()

    with db.get_session() as session:
        # First, count how many articles match
        count_query = """
            SELECT COUNT(*)
            FROM articles
            WHERE status NOT IN ('error', 'proxy_blocked')
            AND (
                {conditions}
            )
        """.format(
            conditions=" OR ".join(
                f"title LIKE '%{pattern}%' OR content LIKE '%{pattern}%'"
                for pattern in PROXY_PATTERNS
            )
        )

        total_count = session.execute(text(count_query)).scalar()
        logger.info(f"Found {total_count} articles with proxy challenge patterns")

        if total_count == 0:
            logger.info("No articles to update")
            return

        # Get examples before updating
        example_query = """
            SELECT id, url, title, status, wire_check_status
            FROM articles
            WHERE status NOT IN ('error', 'proxy_blocked')
            AND (
                {conditions}
            )
            ORDER BY extracted_at DESC
            LIMIT 5
        """.format(
            conditions=" OR ".join(
                f"title LIKE '%{pattern}%' OR content LIKE '%{pattern}%'"
                for pattern in PROXY_PATTERNS
            )
        )

        examples = session.execute(text(example_query)).fetchall()
        logger.info("Examples being updated:")
        for row in examples:
            logger.info(f"  - {row[2][:80]} (status: {row[3]}, wire: {row[4]})")
            logger.info(f"    URL: {row[1]}")

        # Update articles to error status
        update_query = """
            UPDATE articles
            SET status = 'error'
            WHERE status NOT IN ('error', 'proxy_blocked')
            AND (
                {conditions}
            )
        """.format(
            conditions=" OR ".join(
                f"title LIKE '%{pattern}%' OR content LIKE '%{pattern}%'"
                for pattern in PROXY_PATTERNS
            )
        )

        result = session.execute(text(update_query))
        session.commit()

        logger.info(f"✅ Updated {result.rowcount} articles to status='error'")
        logger.info("These articles will no longer be exported to BigQuery")

        # Verify no more would be exported
        verify_query = """
            SELECT COUNT(*)
            FROM articles
            WHERE status = 'labeled'
            AND wire_check_status = 'complete'
            AND (
                {conditions}
            )
        """.format(
            conditions=" OR ".join(
                f"title LIKE '%{pattern}%' OR content LIKE '%{pattern}%'"
                for pattern in PROXY_PATTERNS
            )
        )

        remaining = session.execute(text(verify_query)).scalar()
        if remaining > 0:
            logger.warning(f"⚠️  {remaining} proxy challenge articles still marked for export!")
        else:
            logger.info("✅ No proxy challenge articles will be exported to BigQuery")


if __name__ == "__main__":
    mark_proxy_challenges_as_error()
