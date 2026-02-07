#!/usr/bin/env python3
"""
Promote articles to 'wire' based on strong-tier telemetry in a date range.

Strong-tier criteria:
- content_type_detection_telemetry evidence.detection_tier in {'byline','url','copyright'}

Process:
- Load telemetry rows in window (use detected_at/created_at)
- Parse evidence JSON and collect article_ids with strong-tier
- Filter to articles with publish_date in window and status != 'wire'
- Update articles.status='wire' and wire_check_status='complete' in small batches

Notes:
- Runs inside the production pod (DatabaseManager → Cloud SQL)
"""

import sys
import json
import argparse
import time
from datetime import datetime

sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager

BATCH_SIZE = 200
SLEEP_BETWEEN_CHUNKS = 0.25


def parse_date(s: str) -> datetime:
    try:
        # Accept YYYY-MM-DD or full ISO
        if len(s) == 10:
            return datetime.fromisoformat(s + "T00:00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        raise SystemExit(f"Invalid date: {s}")


def main():
    parser = argparse.ArgumentParser(description="Promote strong-tier telemetry wires within a date range")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD, exclusive)")
    parser.add_argument("--dry-run", action="store_true", help="Do not update, just print summary")
    args = parser.parse_args()

    start_dt = parse_date(args.start)
    end_dt = parse_date(args.end)

    db = DatabaseManager()
    strong_ids = set()

    with db.get_session() as session:
        # Fetch telemetry rows in window
        rows = session.execute(text(
            """
            SELECT article_id, evidence, detected_at, created_at
            FROM content_type_detection_telemetry
            WHERE (status = 'wire' OR detected_type = 'wire')
              AND COALESCE(detected_at, created_at) >= :start
              AND COALESCE(detected_at, created_at) < :end
            ORDER BY COALESCE(detected_at, created_at) DESC
            """
        ), {"start": start_dt, "end": end_dt}).fetchall()

        for (aid, evidence, detected_at, created_at) in rows:
            if not aid:
                continue
            tier = None
            try:
                ev = json.loads(evidence) if isinstance(evidence, str) else evidence
                if isinstance(ev, dict):
                    tier = ev.get("detection_tier")
            except (json.JSONDecodeError, TypeError):
                tier = None
            if tier in {"byline", "url", "copyright"}:
                strong_ids.add(str(aid))

        if not strong_ids:
            print("No strong-tier telemetry rows in window.")
            return

        # Filter to Dec–Jan articles with publish_date in window and not already wire
        candidates = session.execute(text(
            """
            SELECT id, url, status, publish_date
            FROM articles
            WHERE id = ANY(:ids)
              AND publish_date >= :start
              AND publish_date < :end
              AND (status IS NULL OR status <> 'wire')
            ORDER BY publish_date ASC
            """
        ), {"ids": list(strong_ids), "start": start_dt, "end": end_dt}).fetchall()

        print(f"Strong-tier telemetry IDs: {len(strong_ids)} | Updatable articles: {len(candidates)}")

        if args.dry_run or not candidates:
            for r in candidates[:30]:
                print(f"DRY id={r[0]} status={r[2]} pub={r[3]} url={r[1]}")
            return

        updated = 0
        idx = 0
        while idx < len(candidates):
            chunk = candidates[idx: idx + BATCH_SIZE]
            for (aid, url, status, pub_date) in chunk:
                session.execute(text(
                    """
                    UPDATE articles
                    SET status='wire', wire_check_status='complete'
                    WHERE id = :id
                    """
                ), {"id": aid})
            session.commit()
            updated += len(chunk)
            idx += len(chunk)
            print(f"Updated {updated}/{len(candidates)} (last id={chunk[-1][0]})")
            time.sleep(SLEEP_BETWEEN_CHUNKS)

        print(f"Done. Promoted to wire: {updated}")


if __name__ == "__main__":
    main()
