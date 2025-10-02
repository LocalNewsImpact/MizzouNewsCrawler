#!/usr/bin/env python3
"""Manual driver for BalancedBoundaryContentCleaner across selected domains."""

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

# Ensure project source directory is importable before other imports
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cli.commands.extraction import (  # noqa: E402
    _run_post_extraction_cleaning,
)
from models.database import DatabaseManager  # noqa: E402

logger = logging.getLogger("balanced-cleaning")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the BalancedBoundaryContentCleaner against specific domains, "
            "updating article content and status"
        )
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        required=True,
        help="One or more domains to clean (e.g. abc17news.com)",
    )
    parser.add_argument(
        "--status",
        nargs="+",
        default=["extracted", "wire", "pending_clean"],
        help=(
            "Article statuses eligible for cleaning. Default includes "
            "'extracted', 'wire', 'pending_clean'"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of recent articles per domain to clean",
    )
    return parser.parse_args()


def gather_articles(
    session,
    domain: str,
    statuses: list[str],
    limit: int,
) -> list[str]:
    """Return recent article IDs for the domain filtered by status."""
    if not statuses:
        return []

    status_params = {
        f"status_{index}": value for index, value in enumerate(statuses)
    }
    placeholders = ", ".join(f":{key}" for key in status_params)
    query = text(
        f"""
        SELECT id
        FROM articles
        WHERE url LIKE :domain
          AND status IN ({placeholders})
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )
    bound_params = {"domain": f"%{domain}%", "limit": limit, **status_params}
    result = session.execute(query, bound_params)
    return [row[0] for row in result.fetchall()]


def main() -> int:
    args = parse_args()
    db = DatabaseManager()
    session = db.session

    try:
        domain_map: dict[str, list[str]] = defaultdict(list)

        for domain in args.domains:
            article_ids = gather_articles(
                session,
                domain,
                args.status,
                args.limit,
            )
            if not article_ids:
                logger.info(
                    "No articles found for %s with statuses %s",
                    domain,
                    args.status,
                )
                continue

            domain_map[domain] = article_ids
            logger.info(
                "Queued %s articles for domain %s", len(article_ids), domain
            )

        if not domain_map:
            logger.warning("Nothing to clean.")
            return 0

        _run_post_extraction_cleaning(domain_map)
        logger.info(
            "Balanced cleaning complete for %s domains",
            len(domain_map),
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
