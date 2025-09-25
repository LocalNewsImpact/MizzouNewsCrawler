"""
Backfill script: populate `article_uid` on existing rows in backend/reviews.db by
mapping `article_idx` -> articles CSV `id`.
Creates a backup copy of the DB before modifying it.
Run once locally: python3 backend/backfill_article_uids.py
"""

import shutil
import sqlite3
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
ARTICLES_CSV = BASE_DIR / "processed" / "articleslabelledgeo_8.csv"
DB_PATH = BASE_DIR / "backend" / "reviews.db"


def main():
    print("ARTICLES_CSV:", ARTICLES_CSV)
    print("DB_PATH:", DB_PATH)
    if not DB_PATH.exists():
        print("DB not found at", DB_PATH)
        return
    if not ARTICLES_CSV.exists():
        print("Articles CSV not found at", ARTICLES_CSV)
        return

    # make a timestamped backup
    backup = DB_PATH.with_suffix(".db.backup")
    shutil.copy2(DB_PATH, backup)
    print("Backup created at", backup)

    df = pd.read_csv(ARTICLES_CSV)
    # ensure 'id' column exists
    if "id" not in df.columns:
        print("CSV doesn't have 'id' column")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # ensure the column exists (older DBs may not have it)
    cur.execute("PRAGMA table_info(reviews)")
    existing = [r[1] for r in cur.fetchall()]
    if "article_uid" not in existing:
        try:
            cur.execute("ALTER TABLE reviews ADD COLUMN article_uid TEXT")
            conn.commit()
            print("Added article_uid column")
        except Exception as e:
            print("Failed to add article_uid column:", e)
    # find rows missing article_uid
    cur.execute(
        "SELECT id, article_idx, article_uid FROM reviews WHERE article_uid IS NULL OR article_uid = ''"
    )
    rows = cur.fetchall()
    print("Found", len(rows), "rows missing article_uid")
    updated = 0
    for rid, aidx, auid in rows:
        try:
            if aidx is None:
                continue
            aidx_int = int(aidx)
            if 0 <= aidx_int < len(df):
                uid = df.iloc[aidx_int].get("id")
                if uid and uid != "" and uid != "None":
                    cur.execute(
                        "UPDATE reviews SET article_uid=? WHERE id=?", (uid, rid)
                    )
                    updated += 1
        except Exception:
            continue
    conn.commit()
    conn.close()
    print("Updated", updated, "rows")


if __name__ == "__main__":
    main()
