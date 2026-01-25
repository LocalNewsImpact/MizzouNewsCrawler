#!/usr/bin/env python3
"""
Fast wire detection backfill for labeled articles.
Pre-compiles all regex patterns once for speed.
"""

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path if running outside container
if not Path('/app/src').exists():
    sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.models import WireService
from src.models.database import DatabaseManager


class FastWireDetector:
    """Wire detector with pre-compiled patterns for speed."""

    def __init__(self, session):
        """Initialize and pre-compile all patterns."""
        self.session = session
        self.url_patterns = []
        self.author_patterns = []
        self.content_patterns = []

        # Load and compile all patterns once
        print("Loading wire service patterns...")
        patterns = session.query(
            WireService.pattern,
            WireService.service_name,
            WireService.pattern_type,
            WireService.case_sensitive
        ).filter(WireService.active).order_by(WireService.priority).all()

        for pattern, service, ptype, case_sensitive in patterns:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                compiled = re.compile(pattern, flags)
                pattern_tuple = (compiled, service, pattern)

                if ptype == 'url':
                    self.url_patterns.append(pattern_tuple)
                elif ptype == 'author':
                    self.author_patterns.append(pattern_tuple)
                elif ptype == 'content':
                    self.content_patterns.append(pattern_tuple)
            except re.error as e:
                print(f"  Warning: Invalid pattern '{pattern}': {e}")

        print(f"  Loaded {len(self.url_patterns)} URL patterns")
        print(f"  Loaded {len(self.author_patterns)} author patterns")
        print(f"  Loaded {len(self.content_patterns)} content patterns")

    def detect(self, url, author, content):
        """Fast wire detection using pre-compiled patterns."""
        # Check URL patterns first (fastest)
        for pattern, service, _ in self.url_patterns:
            if pattern.search(url):
                return service, "high", "url"

        # Check author patterns
        if author:
            for pattern, service, _ in self.author_patterns:
                if pattern.search(author):
                    return service, "high", "author"

        # Check content patterns (slowest, but necessary)
        # Wire attribution appears at beginning (byline/dateline) or end (copyright/syndication)
        # NOT in the middle of article text
        if content:
            # Search only top 500 chars and bottom 500 chars for attribution/copyright
            top_text = content[:500]
            bottom_text = content[-500:] if len(content) > 500 else ''
            search_text = top_text + ' ' + bottom_text

            for pattern, service, _ in self.content_patterns:
                if pattern.search(search_text):
                    return service, "medium", "content"

        return None, None, None


def main():
    """Run wire detection on all labeled articles."""

    db = DatabaseManager()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"wire_backfill_labeled_{timestamp}.csv"

    print(f"Starting fast wire detection for labeled articles...")
    print(f"Output file: {output_file}")
    print()

    detected_wire = []
    total_processed = 0
    batch_size = 1000

    with db.get_session() as session:
        # Initialize fast detector (pre-compiles all patterns)
        detector = FastWireDetector(session)
        print()

        # Get total count
        total_count = session.execute(text("""
            SELECT COUNT(*)
            FROM articles
            WHERE status = 'labeled' AND wire_check_status = 'complete'
            AND text IS NOT NULL
            AND text != ''
        """)).scalar()

        print(f"Total labeled articles to check: {total_count:,}")
        print()

        offset = 0
        while offset < total_count:
            print(f"Processing batch {offset:,} to {min(offset + batch_size, total_count):,}...")

            # Get batch
            results = session.execute(text("""
                SELECT
                    a.id,
                    a.url,
                    a.title,
                    a.author,
                    a.text as article_text,
                    cl.source
                FROM articles a
                LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
                AND a.text IS NOT NULL
                AND a.text != ''
                ORDER BY a.id
                LIMIT :batch_size OFFSET :offset
            """), {"batch_size": batch_size, "offset": offset}).fetchall()

            if not results:
                break

            for row in results:
                article_id, url, title, author, article_text, source = row
                total_processed += 1

                # Fast wire detection
                service, confidence, tier = detector.detect(
                    url=url or "",
                    author=author or "",
                    content=article_text or ""
                )

                if service:
                    print(f"  🔴 WIRE: {service} ({confidence}) - {(title or '')[:80]}...")

                    detected_wire.append({
                        "article_id": article_id,
                        "url": url,
                        "title": (title or "")[:150],
                        "author": author or "",
                        "source": source or "",
                        "detected_service": service,
                        "detection_tier": tier,
                        "confidence": confidence,
                    })

                if total_processed % 100 == 0:
                    print(f"  Processed {total_processed:,} articles, found {len(detected_wire):,} wire articles")

            offset += batch_size

    # Write results to CSV
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Total articles processed: {total_processed:,}")
    print(f"Wire articles detected: {len(detected_wire):,} ({100.0 * len(detected_wire) / total_processed if total_processed else 0:.2f}%)")
    print()

    if detected_wire:
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ["article_id", "url", "title", "author", "source",
                         "detected_service", "detection_tier", "confidence"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(detected_wire)

        print(f"Results written to: {output_file}")
        print()

        # Show sample
        print("Sample detections (first 10):")
        for i, item in enumerate(detected_wire[:10], 1):
            print(f"\n{i}. {item['detected_service']} (tier: {item['detection_tier']}, confidence: {item['confidence']})")
            print(f"   Title: {item['title']}")
            print(f"   Source: {item['source']}")
    else:
        print("No wire articles detected.")


if __name__ == "__main__":
    main()
