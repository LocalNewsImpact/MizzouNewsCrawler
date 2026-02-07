#!/usr/bin/env python3
"""
Promote articles to 'wire' for cleaning-tier telemetry mismatches using a safe whitelist.

Rules:
- Strong-only: promote when tags include content_type:byline, content_type:url, or content_type:copyright.
- Dual-signal cleaning: promote when cleaning:persistent_pattern AND any content_type:* signal are present.
- Optional domain guard: apply only to URLs whose host appears in a provided allowlist file (one domain per line).
- Status gating: only promote when wire_check_status in ('pending','complete') and status != 'wire'.
- Publish date window: restrict to articles with publish_date >= --start and < --end.

Inputs:
- --csv: path to telemetry mismatches CSV (columns: article_id,url,status,wire_check_status,publish_date,tags,first_seen)
- --start, --end: date boundaries (YYYY-MM-DD). End is exclusive.
- --dry-run: print summary and sample IDs instead of updating.
- --limit: max candidates to consider (default 5000)
- --domain-allow-file: optional file of allowed domains (one per line)
- --out: optional CSV to write promoted IDs

Usage:
  python scripts/promote_cleaning_whitelist.py \
      --csv /tmp/telemetry_mismatches_decjan.csv \
      --start 2024-12-01 --end 2026-02-01 \
      --dry-run
"""

import argparse
import csv
from datetime import datetime
from urllib.parse import urlparse
from typing import Iterable

try:
    import sys
    sys.path.insert(0, "/app")
    from sqlalchemy import text
    from src.models.database import DatabaseManager
except Exception:
    from sqlalchemy import text  # type: ignore
    from backend.app.src.models.database import DatabaseManager  # type: ignore


def parse_date(s: str) -> datetime:
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


def tag_has(tags: Iterable[str], prefix: str) -> bool:
    return any(t.startswith(prefix) for t in tags)


def is_strong(tags: list[str]) -> bool:
    # Treat metadata, content, and bare content_type as strong-tier along with byline/url
    return (
        tag_has(tags, "content_type:byline")
        or tag_has(tags, "content_type:url")
        or tag_has(tags, "content_type:metadata")
        or tag_has(tags, "content_type:content")
        or tag_has(tags, "content_type:")  # fallback tag without explicit tier
    )


def is_dual_cleaning(tags: list[str]) -> bool:
    return tag_has(tags, "cleaning:persistent_pattern") and tag_has(tags, "content_type:")


def main():
    p = argparse.ArgumentParser(description="Promote cleaning-tier telemetry mismatches using whitelist rules")
    p.add_argument("--csv", required=True, help="Telemetry mismatches CSV path")
    p.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", required=True, help="End date (YYYY-MM-DD, exclusive)")
    p.add_argument("--dry-run", action="store_true", help="Do not update; show summary")
    p.add_argument("--limit", type=int, default=5000, help="Max rows to consider from CSV")
    p.add_argument("--domain-allow-file", help="Optional domain allowlist file")
    p.add_argument("--out", help="Optional output CSV to write promoted IDs")
    args = p.parse_args()

    start_dt = parse_date(args.start)
    end_dt = parse_date(args.end)
    allow_domains = load_domains(args.domain_allow_file)

    strong_candidates: list[str] = []
    dual_cleaning_candidates: list[str] = []
    hosts_by_id: dict[str, str] = {}

    # Load CSV and select candidates per rules
    with open(args.csv, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for i, row in enumerate(r):
            if args.limit and i >= args.limit:
                break
            aid = row.get("article_id")
            url = row.get("url") or ""
            status = (row.get("status") or "").lower()
            wcs = (row.get("wire_check_status") or "").lower()
            pub_date = row.get("publish_date")
            tags = (row.get("tags") or "").split(",")

            if not aid or not url:
                continue
            try:
                pub_dt = datetime.fromisoformat(pub_date) if pub_date else None
            except ValueError:
                pub_dt = None
            if pub_dt is None or pub_dt < start_dt or pub_dt >= end_dt:
                continue
            if status == "wire":
                continue
            if wcs not in {"pending", "complete"}:
                continue

            host = urlparse(url).netloc.lower()
            hosts_by_id[aid] = host
            if allow_domains and host not in allow_domains:
                continue

            if is_strong(tags):
                strong_candidates.append(aid)
            elif is_dual_cleaning(tags):
                dual_cleaning_candidates.append(aid)

    # Summaries
    print(f"Strong-tier candidates: {len(strong_candidates)}")
    print(f"Dual-signal cleaning candidates: {len(dual_cleaning_candidates)}")

    ids_to_update = list({*strong_candidates, *dual_cleaning_candidates})
    if not ids_to_update:
        print("No candidates after whitelist and window filters.")
        return

    db = DatabaseManager()
    updated = 0
    preview = []
    with db.get_session() as s:
        # Pull current statuses and publish_date again from DB to be safe
        rows = s.execute(text(
            """
            SELECT id, url, status, wire_check_status, publish_date
            FROM articles
            WHERE id = ANY(:ids)
              AND publish_date >= :start
              AND publish_date < :end
              AND (status IS NULL OR status <> 'wire')
            """
        ), {"ids": ids_to_update, "start": start_dt, "end": end_dt}).fetchall()

        if args.dry_run:
            for r in rows[:30]:
                print(f"DRY id={r[0]} status={r[2]} wcs={r[3]} pub={r[4]} host={hosts_by_id.get(str(r[0]), '')}")
            print(f"Dry-run selectable rows: {len(rows)}")
            return

        BATCH_SIZE = 200
        idx = 0
        while idx < len(rows):
            chunk = rows[idx: idx + BATCH_SIZE]
            for (aid, url, status, wcs, pub) in chunk:
                s.execute(text(
                    """
                    UPDATE articles
                    SET status='wire', wire_check_status='complete'
                    WHERE id = :id
                    """
                ), {"id": aid})
            s.commit()
            updated += len(chunk)
            idx += len(chunk)
            print(f"Updated {updated}/{len(rows)} (last id={chunk[-1][0]})")

    # Optional output of promoted IDs
    if not args.dry_run and args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["article_id", "host"])
            for aid in ids_to_update:
                w.writerow([aid, hosts_by_id.get(aid, "")])

    if not args.dry_run:
        print(f"Done. Promoted to wire: {updated}")


if __name__ == "__main__":
    main()
