#!/usr/bin/env python3
"""Record entity-extraction state on articles instead of deriving it.

Finding pending work used to be an anti-join:

    NOT EXISTS (SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id)

which had to consider the whole corpus to locate the handful of articles still
pending — 150k articles against 2.7M entity rows to find ~80. Cost grew as more
work completed, so the query got slower the further ahead the pipeline got, and
once it crossed the 120s statement_timeout on the mizzou_user role it failed
every cycle. The timeout revealed the problem rather than causing it.

This makes the pending set directly indexable:

  1. ``articles.entities_extracted_at`` (idempotent ADD COLUMN IF NOT EXISTS).
  2. Backfill it for every article that already has entity rows, so switching
     the query does not reprocess 122k articles.
  3. A partial index over exactly the pending predicate. It holds only the rows
     still outstanding and SHRINKS as the queue drains — the opposite of the
     anti-join, which grew.

Order matters: column, then backfill, then index, then deploy the query change.
A half-applied migration must never leave the new query seeing everything as
pending.

Usage:
  python scripts/backfill_entities_extracted_at.py --dry-run
  python scripts/backfill_entities_extracted_at.py
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from src.models.database import DatabaseManager

ADD_COLUMN_SQL = text(
    "ALTER TABLE articles ADD COLUMN IF NOT EXISTS entities_extracted_at TIMESTAMP"
)

# Stamp articles that already have entities. Uses the entity row's own
# created_at where available so the record reflects when work actually
# happened rather than when this script ran.
BACKFILL_SQL = text("""
UPDATE articles a
SET entities_extracted_at = COALESCE(src.first_seen, NOW())
FROM (
    SELECT article_id, MIN(created_at) AS first_seen
    FROM article_entities
    GROUP BY article_id
) src
WHERE a.id = src.article_id
  AND a.entities_extracted_at IS NULL
""")

# Mirrors the candidate query's WHERE clause exactly, so the planner can use it
# for that lookup. CONCURRENTLY keeps writes flowing while it builds.
CREATE_INDEX_SQL = text("""
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_pending_entities
ON articles (candidate_link_id)
WHERE entities_extracted_at IS NULL
  AND content IS NOT NULL
  AND text IS NOT NULL
  AND status NOT IN ('error', 'paywall', 'wire')
""")

PENDING_SQL = """
SELECT COUNT(*) FROM articles a
WHERE a.content IS NOT NULL AND a.text IS NOT NULL
  AND a.status NOT IN ('error', 'paywall', 'wire')
  AND NOT EXISTS (SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id)
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    engine = DatabaseManager().engine

    with engine.begin() as conn:
        # The anti-join this replaces is the slow one, so give it room to run
        # for reporting purposes even though the role caps statements at 120s.
        conn.execute(text("SET statement_timeout='600s'"))

        total = conn.execute(text("SELECT COUNT(*) FROM articles")).scalar() or 0
        with_entities = (
            conn.execute(
                text("SELECT COUNT(DISTINCT article_id) FROM article_entities")
            ).scalar()
            or 0
        )
        pending = conn.execute(text(PENDING_SQL)).scalar() or 0
        print(
            f"articles={total:,}  with_entities={with_entities:,}  pending={pending:,}"
        )

        if args.dry_run:
            print(
                f"DRY RUN: would add entities_extracted_at, stamp {with_entities:,} "
                f"already-processed articles, and index the {pending:,} pending"
            )
            return 0

        conn.execute(ADD_COLUMN_SQL)
        print("column ensured")

        stamped = conn.execute(BACKFILL_SQL).rowcount
        print(f"backfilled entities_extracted_at on {stamped:,} articles")

    # CONCURRENTLY cannot run inside a transaction block.
    with engine.connect() as conn:
        conn.execute(text("COMMIT"))
        conn.execute(text("SET statement_timeout='600s'"))
        conn.execute(CREATE_INDEX_SQL)
        print("partial index ensured (idx_articles_pending_entities)")

    with engine.connect() as conn:
        remaining = (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM articles WHERE entities_extracted_at IS NULL"
                )
            ).scalar()
            or 0
        )
        print(f"articles still unstamped (genuine pending + skipped): {remaining:,}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
