#!/usr/bin/env python3
"""Backfill persistent_boilerplate_patterns.source_id from the URL/domain key.

Boilerplate patterns were historically keyed by the URL-derived ``domain``
string, which is inconsistent (``www.``-prefixed for most rows, bare for
others) and not 1:1 with a source. As a result, learned patterns frequently
never matched at clean time (stored under one domain form, looked up under
another) and two sources sharing a domain collided into one bucket.

This one-off backfill:
  1. Adds the ``source_id`` column to the prod table if missing (Postgres
     ``ADD COLUMN IF NOT EXISTS`` — idempotent, safe to re-run).
  2. Populates ``source_id`` from ``candidate_links``, mapping each pattern's
     stored ``domain`` to a source hostname while tolerating the www/bare
     mismatch. Only domains that map to EXACTLY ONE source are backfilled;
     ambiguous domains (a handful map to 2 sources) are left NULL so they keep
     falling back to domain-keyed lookup rather than being mis-assigned.

Usage:
  python scripts/backfill_boilerplate_source_id.py --dry-run
  python scripts/backfill_boilerplate_source_id.py
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from src.models.database import DatabaseManager

ADD_COLUMN_SQL = text(
    "ALTER TABLE persistent_boilerplate_patterns "
    "ADD COLUMN IF NOT EXISTS source_id TEXT"
)

CREATE_INDEX_SQL = text(
    "CREATE INDEX IF NOT EXISTS idx_persistent_patterns_source "
    "ON persistent_boilerplate_patterns(source_id, is_active)"
)

# Map each pattern.domain to a source_id via the hostnames seen in that
# source's candidate_links, matching www/bare variants both directions.
# Only unambiguous hosts (exactly one source) are used.
BACKFILL_SQL = text("""
WITH host_src AS (
    SELECT DISTINCT
        lower(split_part(regexp_replace(url, '^https?://', ''), '/', 1)) AS host,
        source_id
    FROM candidate_links
    WHERE source_id IS NOT NULL
),
host_unique AS (
    SELECT host, MIN(source_id::text) AS src
    FROM host_src
    GROUP BY host
    HAVING COUNT(DISTINCT source_id) = 1
)
UPDATE persistent_boilerplate_patterns p
SET source_id = h.src
FROM host_unique h
WHERE p.source_id IS NULL
  AND (
        lower(p.domain) = h.host
     OR 'www.' || lower(p.domain) = h.host
     OR lower(p.domain) = 'www.' || h.host
  )
""")


def _scalar(conn, sql: str) -> int:
    return conn.execute(text(sql)).scalar() or 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing (skips ALTER + UPDATE).",
    )
    args = parser.parse_args()

    engine = DatabaseManager().engine
    with engine.begin() as conn:
        total = _scalar(conn, "SELECT COUNT(*) FROM persistent_boilerplate_patterns")
        before_null = _scalar(
            conn,
            "SELECT COUNT(*) FROM persistent_boilerplate_patterns "
            "WHERE source_id IS NULL",
        )
        print(f"patterns total={total}  source_id NULL (before)={before_null}")

        if args.dry_run:
            # Count how many NULL rows WOULD map to a unique source.
            would = conn.execute(text("""
                WITH host_src AS (
                    SELECT DISTINCT
                        lower(split_part(regexp_replace(url,'^https?://',''),'/',1)) AS host,
                        source_id
                    FROM candidate_links WHERE source_id IS NOT NULL
                ),
                host_unique AS (
                    SELECT host, MIN(source_id::text) AS src FROM host_src
                    GROUP BY host HAVING COUNT(DISTINCT source_id) = 1
                )
                SELECT COUNT(*) FROM persistent_boilerplate_patterns p
                JOIN host_unique h ON (
                    lower(p.domain) = h.host
                    OR 'www.' || lower(p.domain) = h.host
                    OR lower(p.domain) = 'www.' || h.host
                )
                WHERE p.source_id IS NULL
            """)).scalar() or 0
            print(
                f"DRY RUN: would backfill {would} rows; "
                f"{before_null - would} would remain NULL (ambiguous/unmatched)"
            )
            return 0

        conn.execute(ADD_COLUMN_SQL)
        conn.execute(CREATE_INDEX_SQL)
        result = conn.execute(BACKFILL_SQL)
        updated = result.rowcount

        after_null = _scalar(
            conn,
            "SELECT COUNT(*) FROM persistent_boilerplate_patterns "
            "WHERE source_id IS NULL",
        )
        print(
            f"backfilled source_id on {updated} rows; "
            f"source_id NULL (after)={after_null}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
