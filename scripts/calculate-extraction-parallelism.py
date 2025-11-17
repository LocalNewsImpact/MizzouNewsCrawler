#!/usr/bin/env python3
"""Calculate optimal extraction parallelism based on backlog size.

Scaling rules:
- 0-99 articles: 1 worker (minimal backlog)
- 100-499 articles: 2 workers (default)
- 500-999 articles: 4 workers (moderate backlog)
- 1000-2499 articles: 6 workers (large backlog)
- 2500+ articles: 10 workers (maximum scale)

Usage:
    python scripts/calculate-extraction-parallelism.py
    # Outputs just the number: 2
"""
import sys
from src.models.database import DatabaseManager
from sqlalchemy import text


def get_extraction_backlog() -> int:
    """Count articles ready for extraction (verified but not extracted)."""
    db = DatabaseManager()
    with db.get_session() as session:
        result = session.execute(
            text(
                """
            SELECT COUNT(*)
            FROM candidate_links cl
            WHERE cl.status = 'article'
            AND cl.id NOT IN (
                SELECT candidate_link_id 
                FROM articles 
                WHERE candidate_link_id IS NOT NULL
            )
        """
            )
        ).scalar()
        return result or 0


def calculate_parallelism(backlog: int) -> int:
    """Calculate optimal number of extraction workers based on backlog size."""
    if backlog < 100:
        return 1
    elif backlog < 500:
        return 2
    elif backlog < 1000:
        return 4
    elif backlog < 2500:
        return 6
    else:
        return 10


def main():
    try:
        backlog = get_extraction_backlog()
        parallelism = calculate_parallelism(backlog)

        # Output to stderr for logging, stdout for capture
        print(f"Backlog: {backlog} articles → {parallelism} workers", file=sys.stderr)
        print(parallelism)  # Just the number for easy capture
        return 0
    except Exception as e:
        print(f"Error calculating parallelism: {e}", file=sys.stderr)
        print(2)  # Default fallback
        return 1


if __name__ == "__main__":
    sys.exit(main())
