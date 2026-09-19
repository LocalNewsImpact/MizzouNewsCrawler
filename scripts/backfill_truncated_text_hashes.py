#!/usr/bin/env python3
"""Recompute the content hashes that were stored truncated.

`calculate_content_hash` returns a full 64-character sha256 and every row the
crawler writes carries that. Two import scripts computed their own hash and cut
it to 32 characters, so 1,041 articles hold a value that cannot equal any
crawler-written hash however identical the text.

What that cost: duplicate detection between an imported body and a fetched one
was impossible for those rows. A Port Townsend Leader search page stored under
two different URLs was found only by eye, because the pair matched each other --
both truncated the same way -- and matched nothing else in the corpus.

The hash is derived from `text`, so this needs no source data: recompute and
write. Rows whose text is empty are left alone, since a hash of nothing is not
a useful key.

Usage:
  python scripts/backfill_truncated_text_hashes.py --dry-run
  python scripts/backfill_truncated_text_hashes.py
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from src.models.database import DatabaseManager, calculate_content_hash

#: The length every crawler-written hash has. Anything shorter was truncated by
#: a caller that computed its own instead of using calculate_content_hash.
FULL_HASH_CHARS = 64

FIND_SQL = text("""
    SELECT id, text
      FROM articles
     WHERE text_hash IS NOT NULL
       AND length(text_hash) < :full
       AND coalesce(text, '') <> ''
     ORDER BY id
     LIMIT :limit
""")

UPDATE_SQL = text("UPDATE articles SET text_hash = :hash WHERE id = :id")

COUNT_SQL = text("""
    SELECT length(text_hash) AS chars,
           count(*) AS rows,
           count(*) FILTER (WHERE coalesce(text, '') = '') AS empty_text
      FROM articles
     WHERE text_hash IS NOT NULL
     GROUP BY 1
     ORDER BY 2 DESC
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = DatabaseManager()
    with db.get_session() as session:
        print("hash lengths before:")
        for row in session.execute(COUNT_SQL).all():
            print(f"  {row[0]:>3} chars  {row[1]:>7} rows  ({row[2]} with empty text)")

        rows = session.execute(
            FIND_SQL, {"full": FULL_HASH_CHARS, "limit": args.limit}
        ).all()
        print(f"\n{len(rows)} row(s) to recompute")
        if not rows:
            return 0

        changed = same = 0
        for article_id, body in rows:
            new_hash = calculate_content_hash(body)
            if args.dry_run:
                changed += 1
                continue
            session.execute(UPDATE_SQL, {"hash": new_hash, "id": article_id})
            changed += 1
        if args.dry_run:
            print(f"--dry-run: would rewrite {changed}, nothing written")
            return 0
        session.commit()
        print(f"rewrote {changed} (unchanged {same})")

        print("\nhash lengths after:")
        for row in session.execute(COUNT_SQL).all():
            print(f"  {row[0]:>3} chars  {row[1]:>7} rows")

        # What the fix unlocks: bodies that are byte-identical across URLs on one
        # host, which a truncated hash could not have joined to a fetched row.
        dupes = session.execute(text("""
            SELECT count(*) FROM (
              SELECT a.text_hash, s.host
                FROM articles a
                JOIN candidate_links cl ON cl.id = a.candidate_link_id
                JOIN sources s ON s.id = cl.source_id
               WHERE a.text_hash IS NOT NULL AND coalesce(a.text_length, 0) > 0
               GROUP BY 1, 2 HAVING count(*) > 1) t
            """)).scalar()
        print(f"\nsame-host duplicate-body groups now visible: {dupes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
