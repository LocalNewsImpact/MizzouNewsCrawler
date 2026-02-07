#!/usr/bin/env python3
"""
Audit wire telemetry vs current article statuses.

Pulls affirmative wire detections from:
- content_type_detection_telemetry (status/detected_type = 'wire')
- content_cleaning_wire_events (any provider/stage)

Then compares against `articles.status`, listing mismatches where
telemetry indicates wire but article.status != 'wire'.
"""

import sys
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import json

sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager


def parse_cutoff(days: int | None, since: str | None) -> datetime:
    if since:
        try:
            return datetime.fromisoformat(since)
        except ValueError:
            # Accept date-only
            return datetime.fromisoformat(since + "T00:00:00")
    if days is None:
        days = 7
    return datetime.utcnow() - timedelta(days=days)


def main():
    parser = argparse.ArgumentParser(description="Audit wire telemetry mismatches vs articles table")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default 7)")
    parser.add_argument("--since", help="ISO date/time (YYYY-MM-DD or full timestamp) overrides --days")
    parser.add_argument("--limit", type=int, default=2000, help="Max telemetry rows to consider")
    args = parser.parse_args()

    cutoff = parse_cutoff(args.days, args.since)

    db = DatabaseManager()
    with db.get_session() as session:
        # 1) Content-type telemetry (wire classifications)
        ct_rows = session.execute(text(
            """
            SELECT article_id, url, status, reason, evidence, version, created_at
            FROM content_type_detection_telemetry
            WHERE (status = 'wire' OR detected_type = 'wire')
              AND created_at >= :cutoff
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ), {"cutoff": cutoff, "limit": args.limit}).fetchall()

        # 2) Content-cleaning wire events (domain/persistent/inline)
        cc_rows = session.execute(text(
            """
            SELECT provider, detection_method, detection_stage,
                   confidence, article_ids_json, timestamp
            FROM content_cleaning_wire_events
            WHERE timestamp >= :cutoff
            ORDER BY timestamp DESC
            LIMIT :limit
            """
        ), {"cutoff": cutoff, "limit": args.limit}).fetchall()

        # Build set of article IDs flagged as wire by telemetry
        wire_ids: set[str] = set()
        wire_evidence: dict[str, list[str]] = defaultdict(list)

        for (aid, url, status, reason, evidence, version, created_at) in ct_rows:
            if not aid:
                continue
            wire_ids.add(str(aid))
            try:
                ev = json.loads(evidence) if isinstance(evidence, str) else evidence
            except (json.JSONDecodeError, TypeError):
                ev = None
            tier = None
            if isinstance(ev, dict):
                tier = ev.get("detection_tier")
            if tier:
                wire_evidence[str(aid)].append(f"content_type:{tier}")
            else:
                wire_evidence[str(aid)].append("content_type")

        for (provider, method, stage, confidence, article_ids_json, ts) in cc_rows:
            try:
                ids = json.loads(article_ids_json) if article_ids_json else []
            except (json.JSONDecodeError, TypeError):
                ids = []
            for aid in ids or []:
                wire_ids.add(str(aid))
                tag = f"cleaning:{stage or method or provider or 'wire'}"
                wire_evidence[str(aid)].append(tag)

        if not wire_ids:
            print("No wire telemetry found in window.")
            return

        # Fetch current article statuses for those IDs
        rows = session.execute(text(
            """
            SELECT id, url, status, wire_check_status
            FROM articles
            WHERE id = ANY(:ids)
            """
        ), {"ids": list(wire_ids)}).fetchall()

        mismatches = []
        for (aid, url, status, wire_check_status) in rows:
            if (status or '').lower() != 'wire':
                mismatches.append((str(aid), url, status, wire_check_status, 
                                   ",".join(wire_evidence.get(str(aid), []))))

        print(f"Telemetry wire IDs: {len(wire_ids)} | Mismatches: {len(mismatches)}")
        for (aid, url, status, wcs, tags) in mismatches[:50]:
            print(f"MISS id={aid} status={status} wire_check_status={wcs} tags=[{tags}] url={url}")


if __name__ == "__main__":
    main()
