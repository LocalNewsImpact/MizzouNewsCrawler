#!/usr/bin/env python3
"""Migration: add `publish_date` DateTime column to candidate_links and
backfill from existing `meta` JSON.

Usage: python scripts/migrations/add_publish_date_to_candidate_links.py --db sqlite:///data/mizzou.db

Notes:
- This script is conservative: it will only ALTER TABLE if the column is
  missing.
- Backfill attempts to parse ISO-formatted strings found in
  `meta->publish_date`.
"""

import argparse
import json
import logging
import random
import sqlite3
import time
from datetime import datetime

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def _retry_pragma(conn, table_name: str, max_attempts: int = 5):
    """Execute PRAGMA table_info with retries for transient locks.

    Returns list of column names or empty list on failure.
    """
    attempts = 0
    backoff = 0.05
    while attempts < max_attempts:
        try:
            res = conn.execute(text(f"PRAGMA table_info({table_name})"))
            return [r[1] for r in res.fetchall()]
        except Exception as e:
            msg = str(e).lower()
            if "database is locked" in msg and attempts < max_attempts - 1:
                time.sleep(backoff + (random.random() * backoff))
                backoff *= 2
                attempts += 1
                continue
            raise
    return []


def has_column(engine, table_name: str, column_name: str) -> bool:
    try:
        with engine.connect() as conn:
            cols = _retry_pragma(conn, table_name)
            return column_name in cols
    except Exception:
        return False


def add_column(engine, table_name: str, column_def: str):
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_def}"
    logger.info("Executing: %s", sql)

    max_attempts = 6
    backoff = 0.1
    attempts = 0
    while attempts < max_attempts:
        try:
            # Use a raw DBAPI connection to perform BEGIN IMMEDIATE and ALTER
            # outside of SQLAlchemy's transactional context (avoids
            # "cannot start a transaction within a transaction").
            rc = engine.raw_connection()
            cur = rc.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(sql)
                rc.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    rc.close()
                except Exception:
                    pass
            return
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg and attempts < max_attempts - 1:
                sleep_for = backoff + (random.random() * backoff)
                logger.warning(
                    "ALTER TABLE locked, retrying in %.2fs (attempt %d/%d)",
                    sleep_for,
                    attempts + 1,
                    max_attempts,
                )
                time.sleep(sleep_for)
                backoff *= 2
                attempts += 1
                continue
            raise
        except Exception:
            # Any other exception: ensure raw connection closed if present
            try:
                rc.close()
            except Exception:
                pass
            raise


def backfill_publish_dates(engine):
    logger.info("Backfilling publish_date from candidate_links.meta JSON")
    with engine.connect() as conn:
        res = conn.execute(
            text("SELECT id, meta FROM candidate_links WHERE meta IS NOT NULL")
        )
        rows = res.fetchall()
        updated = 0
        for r in rows:
            cl_id = r[0]
            meta = r[1]
            if not meta:
                continue
            try:
                if isinstance(meta, str):
                    # meta may be a JSON string or a plain date string. Try JSON first.
                    try:
                        meta_obj = json.loads(meta)
                        pd = meta_obj.get("publish_date") or meta_obj.get(
                            "published_date"
                        )
                    except Exception:
                        # Not JSON – treat meta itself as the candidate publish_date
                        pd = meta.strip()
                else:
                    meta_obj = meta
                    pd = meta_obj.get("publish_date") or meta_obj.get("published_date")
            except Exception:
                continue
            if not pd:
                continue
            parsed = None
            try:
                parsed = datetime.fromisoformat(pd)
            except Exception:
                try:
                    # dateutil is optional; if present, use it as fallback
                    from dateutil import parser as dateparser

                    parsed = dateparser.parse(pd)
                except Exception:
                    parsed = None
            if not parsed:
                continue
            try:
                update_sql = (
                    "UPDATE candidate_links SET publish_date = :pd " "WHERE id = :id"
                )
                conn.execute(
                    text(update_sql),
                    {"pd": parsed.isoformat(), "id": cl_id},
                )
                conn.commit()
                updated += 1
            except Exception as e:
                logger.warning("Failed to update publish_date for %s: %s", cl_id, e)
        logger.info("Backfilled publish_date for %d rows", updated)


def main():
    parser = argparse.ArgumentParser(
        description=("Add publish_date to candidate_links and backfill from meta JSON")
    )
    parser.add_argument(
        "--db",
        default="sqlite:///data/mizzou.db",
        help="Database URL",
    )
    args = parser.parse_args()

    engine = create_engine(
        args.db,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    if has_column(engine, "candidate_links", "publish_date"):
        logger.info("candidate_links.publish_date exists; skipping alter")
    else:
        logger.info("Adding publish_date column to candidate_links")
        add_column(engine, "candidate_links", "publish_date DATETIME")

    backfill_publish_dates(engine)


if __name__ == "__main__":
    main()
