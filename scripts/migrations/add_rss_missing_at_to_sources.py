"""
Add `rss_missing_at` TIMESTAMP column to `sources` and backfill from
`metadata -> rss_missing` if present. This script is conservative and will
attempt ALTER TABLE; on SQLite it will use a safe approach.

Usage: python scripts/migrations/add_rss_missing_at_to_sources.py
"""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/mizzou.db")

SQL_ADD_COLUMN = "ALTER TABLE sources ADD COLUMN rss_missing_at TIMESTAMP NULL"


def main():
    if not DB_PATH.exists():
        print("Database file not found:", DB_PATH)
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Check if column exists
    cur.execute("PRAGMA table_info(sources)")
    cols = [r[1] for r in cur.fetchall()]
    if "rss_missing_at" in cols:
        print("rss_missing_at already exists, exiting")
        conn.close()
        return

    try:
        cur.execute(SQL_ADD_COLUMN)
        conn.commit()
        print("Added rss_missing_at column")
    except Exception as e:
        print("Could not ALTER TABLE (SQLite may require table rebuild):", e)
        conn.close()
        return

    # Backfill from metadata if present
    cur.execute("SELECT id, metadata FROM sources")
    rows = cur.fetchall()
    updated = 0
    for r in rows:
        sid, meta = r
        if not meta:
            continue
        try:
            if isinstance(meta, str):
                m = json.loads(meta)
            else:
                m = meta
        except Exception:
            continue
        rss_missing = m.get("rss_missing")
        if rss_missing:
            try:
                # try ISO parse
                dt = datetime.fromisoformat(rss_missing)
                cur.execute(
                    "UPDATE sources SET rss_missing_at = ? WHERE id = ?",
                    (dt.isoformat(), sid),
                )
                updated += 1
            except Exception:
                continue

    conn.commit()
    print(f"Backfilled {updated} rows")
    conn.close()


if __name__ == "__main__":
    main()
