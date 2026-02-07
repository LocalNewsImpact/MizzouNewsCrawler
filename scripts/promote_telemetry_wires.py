#!/usr/bin/env python3
"""
Promote articles to 'wire' wherever telemetry indicates WIRE, regardless of tier.

Sources:
- content_type_detection_telemetry: rows with status='wire' or detected_type='wire'
- content_cleaning_wire_events: article_ids_json entries (assumed wire events)

Behavior:
- Computes UNION of telemetry article_ids
- Finds corresponding articles not currently status='wire'
- Updates to status='wire' and wire_check_status='complete'

Options:
- --dry-run: preview counts and sample IDs only, no writes
- --limit: cap rows read from each telemetry table (default 200000)
- --out: optional CSV path (article_id,url,host) of updated candidates
- --start/--end: optional publish_date filters (YYYY-MM-DD). Omit to use full DB

Note: Uses per-row operations to avoid array-param typing issues in raw SQL.
"""

import argparse
import csv
import json
from datetime import datetime
from urllib.parse import urlparse

import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from src.models.database import DatabaseManager


def parse_date_opt(s: str | None) -> datetime | None:
    if not s:
        return None
    if len(s) == 10:
        return datetime.fromisoformat(s + "T00:00:00")
    return datetime.fromisoformat(s)


def main():
    p = argparse.ArgumentParser(description="Promote telemetry-indicated wire articles")
    p.add_argument("--dry-run", action="store_true", help="Preview only; no updates")
    p.add_argument("--limit", type=int, default=200000, help="Max rows to read from each telemetry table")
    p.add_argument("--out", help="Optional CSV path to write updated candidates")
    p.add_argument("--start", help="Optional start publish_date (YYYY-MM-DD)")
    p.add_argument("--end", help="Optional end publish_date (YYYY-MM-DD, exclusive)")
    p.add_argument("--progress-interval", type=int, default=1000, help="Print progress every N items processed")
    args = p.parse_args()

    start_dt = parse_date_opt(args.start)
    end_dt = parse_date_opt(args.end)

    db = DatabaseManager()
    with db.get_session() as session:
        # Content-type telemetry IDs
        ct_ids = set()
        ct_rows = session.execute(text(
            """
            SELECT article_id
            FROM content_type_detection_telemetry
            WHERE (status = 'wire' OR detected_type = 'wire')
            ORDER BY COALESCE(detected_at, created_at) DESC
            LIMIT :limit
            """
        ), {"limit": args.limit}).fetchall()
        print(f"[CT] Fetched {len(ct_rows)} telemetry rows", flush=True)
        for i, (aid,) in enumerate(ct_rows, 1):
            if aid:
                ct_ids.add(str(aid))
            if i % args.progress_interval == 0:
                print(f"[CT] Processed {i}/{len(ct_rows)} | unique ids: {len(ct_ids)}", flush=True)

        # Cleaning telemetry IDs
        cl_ids = set()
        cl_rows = session.execute(text(
            """
            SELECT article_ids_json
            FROM content_cleaning_wire_events
            ORDER BY timestamp DESC
            LIMIT :limit
            """
        ), {"limit": args.limit}).fetchall()
        print(f"[CL] Fetched {len(cl_rows)} cleaning telemetry rows", flush=True)
        for i, (ids_json,) in enumerate(cl_rows, 1):
            try:
                ids = json.loads(ids_json) if ids_json else []
            except (TypeError, json.JSONDecodeError):
                ids = []
            for aid in ids or []:
                cl_ids.add(str(aid))
            if i % args.progress_interval == 0:
                print(f"[CL] Processed {i}/{len(cl_rows)} | unique ids: {len(cl_ids)}", flush=True)

        all_ids = list(ct_ids.union(cl_ids))
        if not all_ids:
            print("No telemetry-indicated wire IDs found.")
            return
        print(f"[UNION] Total unique telemetry article_ids: {len(all_ids)}", flush=True)

        # Determine candidates: articles where status != 'wire' (optionally date-gated)
        candidates = []
        for j, aid in enumerate(all_ids, 1):
            row = session.execute(text(
                """
                SELECT id, url, status, wire_check_status, publish_date
                FROM articles WHERE id = :id
                """
            ), {"id": aid}).fetchone()
            if not row:
                continue
            _id, url, status, wcs, pub = row
            if status == 'wire':
                continue
            if start_dt and (pub is None or pub < start_dt):
                continue
            if end_dt and (pub is None or pub >= end_dt):
                continue
            candidates.append((_id, url, status, wcs, pub))
            if j % args.progress_interval == 0:
                print(f"[SCAN] Checked {j}/{len(all_ids)} | updatable so far: {len(candidates)}", flush=True)

        print(f"Telemetry wire IDs: {len(all_ids)} | Updatable articles: {len(candidates)}", flush=True)
        for c in candidates[:30]:
            host = urlparse((c[1] or "")).netloc
            print(f"SAMPLE id={c[0]} status={c[2]} wcs={c[3]} pub={c[4]} host={host}")

        if args.dry_run or not candidates:
            print("Dry-run: no updates applied.")
            return

        # Update in batches
        updated = 0
        BATCH = 200
        out_rows = []
        i = 0
        while i < len(candidates):
            chunk = candidates[i:i+BATCH]
            for (_id, url, _status, _wcs, _pub) in chunk:
                session.execute(text(
                    """
                    UPDATE articles
                    SET status='wire', wire_check_status='complete'
                    WHERE id = :id
                    """
                ), {"id": _id})
                host = urlparse((url or "")).netloc
                out_rows.append((_id, url, host))
            session.commit()
            updated += len(chunk)
            i += len(chunk)
            print(f"Updated {updated}/{len(candidates)} (last id={chunk[-1][0]})", flush=True)

        if args.out:
            with open(args.out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["article_id", "url", "host"])
                for r in out_rows:
                    w.writerow(list(r))

        print(f"Done. Promoted to wire: {updated}", flush=True)


if __name__ == "__main__":
    main()
