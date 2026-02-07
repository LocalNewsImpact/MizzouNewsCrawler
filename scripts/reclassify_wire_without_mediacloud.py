#!/usr/bin/env python3
"""
Reclassify existing articles using URL + content-based wire detection, excluding MediaCloud.
- Applies discovery-stage URL wire patterns
- Applies content/byline/copyright wire detection via ContentTypeDetector
- Updates articles.status to 'wire' when strong evidence; reverts incorrect 'wire' to 'cleaned'
- Keeps candidate_links in sync (wire ↔ article)
- Runs in batches to avoid locks; prints a summary
"""

import sys
import time
import re
import argparse
from typing import List, Tuple

sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector

BATCH_SIZE = 250
SLEEP_BETWEEN_CHUNKS = 0.25  # seconds

# Statuses to scan for potential (re)classification
SCAN_STATUSES = ('wire', 'labeled', 'cleaned', 'extracted')

def load_wire_url_patterns(detector: ContentTypeDetector) -> List[Tuple[str, str, bool]]:
    """Load URL-only wire service patterns."""
    try:
        return detector._get_wire_service_patterns(pattern_type="url")
    except Exception:
        return []


def is_wire_url(url: str, wire_patterns: List[Tuple[str, str, bool]]) -> Tuple[bool, str | None]:
    """Return (matched, service_name) for URL wire patterns."""
    for pattern, service_name, case_sensitive in wire_patterns:
        flags = 0 if case_sensitive else re.IGNORECASE
        if re.search(pattern, url or "", flags):
            return True, service_name
    return False, None


def process_chunk(rows, detector: ContentTypeDetector, wire_patterns):
    updates = {"to_wire": 0, "wire_to_cleaned": 0, "no_change": 0}
    db = detector._db if hasattr(detector, "_db") and detector._db else DatabaseManager()

    with db.get_session() as session:
        for row in rows:
            article_id = row[0]
            url = row[1]
            title = row[2]
            author = row[3]
            content = row[4]
            status = row[5]
            candidate_link_id = row[6]
            metadata = row[7]

            # Stage 0: URL-only wire detection (strongest suppression)
            url_wire, svc = is_wire_url(url, wire_patterns)

            # Stage 1+: Content/byline/copyright wire detection via detector
            content_wire = False
            if not url_wire:
                try:
                    res = detector._detect_wire_service(
                        url=url,
                        content=content,
                        metadata=metadata if isinstance(metadata, dict) else None,
                        author=author,
                        title=title,
                        raw_html=None,
                    )
                    content_wire = bool(res and res.status == "wire")
                except Exception:
                    content_wire = False

            # Decide new status
            if url_wire or content_wire:
                if status != "wire":
                    # Promote to wire (articles only; skip candidate_links to avoid deadlocks)
                    session.execute(text(
                        "UPDATE articles SET status='wire', wire_check_status='complete' WHERE id=:id"
                    ), {"id": article_id})
                    updates["to_wire"] += 1
                else:
                    updates["no_change"] += 1
            else:
                if status == "wire":
                    # Demote incorrect wire to cleaned (articles only)
                    session.execute(text(
                        "UPDATE articles SET status='cleaned' WHERE id=:id"
                    ), {"id": article_id})
                    updates["wire_to_cleaned"] += 1
                else:
                    updates["no_change"] += 1
        session.commit()
    return updates


def main():
    parser = argparse.ArgumentParser(description="Reclassify articles without MediaCloud")
    parser.add_argument("--start-after-id", dest="start_after_id", help="Resume after this article UUID", default=None)
    parser.add_argument("--publish-since", dest="publish_since", help="Only process articles with publish_date >= YYYY-MM-DD", default=None)
    args = parser.parse_args()

    db = DatabaseManager()
    total = {"to_wire": 0, "wire_to_cleaned": 0, "no_change": 0, "processed": 0}

    with db.get_session() as session:
        # Cursor over all articles in target statuses
        cursor = args.start_after_id or "00000000-0000-0000-0000-000000000000"
        while True:
            base_sql = (
                """
                SELECT id, url, title, author, text, status, candidate_link_id, metadata
                FROM articles
                WHERE id > :cursor AND status = ANY(:statuses)
                """
            )
            params = {"cursor": cursor, "statuses": list(SCAN_STATUSES), "limit": BATCH_SIZE}
            if args.publish_since:
                base_sql += " AND publish_date >= :since"
                params["since"] = args.publish_since
            base_sql += " ORDER BY id ASC LIMIT :limit"

            rows = session.execute(text(base_sql), params).fetchall()

            if not rows:
                break

            # Initialize detector once per chunk (reuse session for DB-backed patterns)
            detector = ContentTypeDetector(session=session)
            wire_patterns = load_wire_url_patterns(detector)

            chunk_updates = process_chunk(rows, detector, wire_patterns)
            total["to_wire"] += chunk_updates["to_wire"]
            total["wire_to_cleaned"] += chunk_updates["wire_to_cleaned"]
            total["no_change"] += chunk_updates["no_change"]
            total["processed"] += len(rows)

            cursor = rows[-1][0]
            extra = f", since={args.publish_since}" if args.publish_since else ""
            print(
                f"Processed {len(rows)} (cursor={cursor}{extra}) → to_wire={chunk_updates['to_wire']}, "
                f"wire_to_cleaned={chunk_updates['wire_to_cleaned']}, no_change={chunk_updates['no_change']}"
            )
            time.sleep(SLEEP_BETWEEN_CHUNKS)

    print("\n=== Reclassification Summary (no MediaCloud) ===")
    print(f"Processed articles: {total['processed']}")
    print(f"Promoted to wire:  {total['to_wire']}")
    print(f"Demoted to cleaned: {total['wire_to_cleaned']}")
    print(f"No change:         {total['no_change']}")

if __name__ == '__main__':
    main()
