#!/usr/bin/env python3
"""
Deduplicate the reviews table in backend/reviews.db.

Keeps the newest row (by created_at) for each (article_idx, reviewer) and
deletes older duplicates. After deduplication, it creates a unique index on
(article_idx, reviewer).

Run: python3 backend/dedupe_reviews.py
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DB = BASE / "backend" / "reviews.db"


def main():
    if not DB.exists():
        print(f"DB not found at {DB}")
        return 1
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    # Find duplicate groups
    cur.execute(
        "SELECT article_idx, reviewer, COUNT(*) as cnt FROM reviews GROUP BY article_idx, reviewer HAVING cnt > 1"
    )
    groups = cur.fetchall()
    print(f"Found {len(groups)} duplicate groups")

    total_deleted = 0
    for article_idx, reviewer, cnt in groups:
        # select ids ordered by created_at desc (newest first)
        cur.execute(
            (
                "SELECT id, created_at FROM reviews "
                "WHERE article_idx=? AND reviewer=? ORDER BY datetime(created_at) DESC, id DESC"
            ),
            (article_idx, reviewer),
        )
        rows = cur.fetchall()
        # keep the first (newest) id
        keep_id = rows[0][0]
        delete_ids = [r[0] for r in rows[1:]]
        if delete_ids:
            q = "DELETE FROM reviews WHERE id IN ({})".format(
                ",".join("?" for _ in delete_ids)
            )
            cur.execute(q, delete_ids)
            deleted = cur.rowcount
            total_deleted += deleted
            print(
                f"Article {article_idx} reviewer '{reviewer}': deleted {deleted} older rows, kept id {keep_id}"
            )

    conn.commit()

    # Try to create unique index
    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS reviews_article_reviewer_idx ON reviews(article_idx, reviewer)"
        )
        conn.commit()
        print("Created unique index reviews_article_reviewer_idx")
    except Exception as e:
        print("Failed creating unique index:", e)
        conn.close()
        return 2

    conn.close()
    print(f"Dedup complete, total deleted rows: {total_deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
