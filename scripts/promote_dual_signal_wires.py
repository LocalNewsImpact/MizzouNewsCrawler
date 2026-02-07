#!/usr/bin/env python3
"""
Promote articles to 'wire' across the full DB using dual-signal evidence:
- content_type_detection_telemetry indicates wire for the article (any tier)
- AND content_cleaning_wire_events includes the article (persistent/inline/domain stages)

Optional filters:
- publish_date window via --start/--end (YYYY-MM-DD, end exclusive); omit to use full DB
- domain allowlist file via --domain-allow-file (one host per line), to restrict changes to known-wire domains
- dry-run to preview counts and sample rows

Outputs:
- Summary to stdout
- Optional CSV of promoted IDs with hosts via --out
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


def load_domains(path: str | None) -> set[str]:
    if not path:
        return set()
    domains = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            d = line.strip()
            if d:
                domains.add(d.lower())
    return domains


def main():
    p = argparse.ArgumentParser(description="Promote dual-signal wire articles across full DB")
    p.add_argument("--start", help="Start date YYYY-MM-DD (publish_date)")
    p.add_argument("--end", help="End date YYYY-MM-DD (publish_date, exclusive)")
    p.add_argument("--dry-run", action="store_true", help="Do not update; preview only")
    p.add_argument("--limit", type=int, default=100000, help="Max telemetry rows per table to consider")
    p.add_argument("--domain-allow-file", help="Optional domain allowlist file")
    p.add_argument("--out", help="Optional CSV path to write promoted IDs")
    args = p.parse_args()

    start_dt = parse_date_opt(args.start)
    end_dt = parse_date_opt(args.end)
    allow_domains = load_domains(args.domain_allow_file)

    db = DatabaseManager()
    with db.get_session() as session:
        # 1) Content-type telemetry wires
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
        for (aid,) in ct_rows:
            if aid:
                ct_ids.add(str(aid))

        # 2) Cleaning telemetry wires (expand JSON arrays)
        cl_ids = set()
        cl_rows = session.execute(text(
            """
            SELECT article_ids_json
            FROM content_cleaning_wire_events
            ORDER BY timestamp DESC
            LIMIT :limit
            """
        ), {"limit": args.limit}).fetchall()
        for (ids_json,) in cl_rows:
            try:
                ids = json.loads(ids_json) if ids_json else []
            except (TypeError, json.JSONDecodeError):
                ids = []
            for aid in ids or []:
                cl_ids.add(str(aid))

        # Dual-signal intersection
        dual_ids = list(ct_ids.intersection(cl_ids))
        if not dual_ids:
            print("No dual-signal candidates found.")
            return

        # Fetch candidate articles (apply status/date filters, optional domain allowlist)
        rows = session.execute(text(
            """
            SELECT id, url, status, wire_check_status, publish_date
            FROM articles
            WHERE id = ANY(:ids)
              AND (status IS NULL OR status <> 'wire')
            """
        ), {"ids": dual_ids}).fetchall()

        candidates = []
        for (aid, url, status, wcs, pub) in rows:
            if start_dt and (pub is None or pub < start_dt):
                continue
            if end_dt and (pub is None or pub >= end_dt):
                continue
            if wcs and wcs.lower() not in {"pending", "complete"}:
                continue
            host = urlparse(url or "").netloc.lower()
            if allow_domains and host not in allow_domains:
                continue
            candidates.append((aid, url, status, wcs, pub, host))

        print(f"Dual-signal telemetry IDs: {len(dual_ids)} | Updatable candidates: {len(candidates)}")
        for c in candidates[:30]:
            print(f"SAMPLE id={c[0]} status={c[2]} wcs={c[3]} pub={c[4]} host={c[5]}")

        if args.dry_run or not candidates:
            print("Dry-run: no updates applied.")
            return

        # Perform updates in batches
        updated = 0
        BATCH_SIZE = 200
        idx = 0
        while idx < len(candidates):
            chunk = candidates[idx: idx + BATCH_SIZE]
            for (aid, _url, _status, _wcs, _pub, _host) in chunk:
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

        if args.out:
            with open(args.out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["article_id", "host"])
                for (aid, _url, _status, _wcs, _pub, host) in candidates:
                    w.writerow([aid, host])

        print(f"Done. Promoted to wire: {updated}")


if __name__ == "__main__":
    main()
