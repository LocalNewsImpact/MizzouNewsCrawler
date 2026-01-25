#!/usr/bin/env python3
"""
Quick wire detection dry-run for labeled articles.
Processes in small batches and exports to CSV.
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path only if running outside container
if not Path('/app/src').exists():
    sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector


def main():
    """Run wire detection on labeled articles and export to CSV."""

    db = DatabaseManager()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"wire_backfill_labeled_{timestamp}.csv"

    print(f"Starting wire detection dry-run for labeled articles...")
    print(f"Output file: {output_file}")
    print()

    detected_wire = []
    total_processed = 0
    batch_size = 500

    with db.get_session() as session:
        # Initialize detector with session to cache patterns
        detector = ContentTypeDetector(session=session)
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

                # Run wire detection
                result = detector._detect_wire_service(
                    url=url,
                    content=article_text or "",
                    metadata={"author": author}
                )

                if result and result.status == "wire":
                    services = result.evidence.get("detected_services", [])
                    service = services[0] if services else "Unknown"
                    tier = result.evidence.get("detection_tier", "unknown")

                    # Log each wire detection
                    print(f"  🔴 WIRE: {service} ({result.confidence}) - {(title or '')[:80]}...")

                    detected_wire.append({
                        "article_id": article_id,
                        "url": url,
                        "title": (title or "")[:150],
                        "author": author or "",
                        "source": source or "",
                        "detected_service": service,
                        "detection_tier": tier,
                        "confidence": result.confidence,
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
