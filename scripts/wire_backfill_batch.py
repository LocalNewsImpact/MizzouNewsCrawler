#!/usr/bin/env python3
"""
Efficient batched wire detection backfill with CSV export.
Processes articles in batches to avoid memory issues.
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text as sql_text


def main():
    db = DatabaseManager()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv = f"labeled_to_wire_candidates_{timestamp}.csv"

    print(f"Starting wire detection dry-run backfill")
    print(f"Output: {output_csv}")
    print()

    total_checked = 0
    total_wire = 0
    batch_size = 500

    with open(output_csv, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            'article_id', 'url', 'title', 'author', 'source',
            'detected_service', 'confidence', 'detection_tier', 'reason'
        ])

        with db.get_session() as session:
            detector = ContentTypeDetector(session=session)

            # Get total count
            total = session.execute(sql_text("""
                SELECT COUNT(*)
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
                AND a.text IS NOT NULL
                AND a.text != ''
            """)).scalar()

            print(f"Total articles to check: {total:,}")
            print()

            offset = 0
            while offset < total:
                # Process batch
                results = session.execute(sql_text("""
                    SELECT
                        a.id,
                        a.url,
                        a.title,
                        a.author,
                        a.text,
                        cl.source
                    FROM articles a
                    JOIN candidate_links cl ON a.candidate_link_id = cl.id
                    WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
                    AND a.text IS NOT NULL
                    AND a.text != ''
                    ORDER BY a.id
                    LIMIT :batch_size OFFSET :offset
                """), {"batch_size": batch_size, "offset": offset}).fetchall()

                if not results:
                    break

                for row in results:
                    total_checked += 1
                    article_id, url, title, author, text, source = row

                    # Run detection
                    result = detector._detect_wire_service(
                        url=url,
                        content=text or title or "",
                        metadata={"author": author}
                    )

                    if result and result.status == "wire":
                        total_wire += 1

                        services = result.evidence.get("detected_services", [])
                        service = services[0] if services else "Unknown"
                        tier = result.evidence.get("detection_tier", "unknown")

                        writer.writerow([
                            article_id,
                            url,
                            title[:100] if title else "",
                            author or "",
                            source,
                            service,
                            result.confidence,
                            tier,
                            result.reason[:200] if result.reason else ""
                        ])

                    if total_checked % 100 == 0:
                        print(f"Checked {total_checked:,}/{total:,} - Wire detected: {total_wire:,}", end='\r')

                offset += batch_size

    print()
    print()
    print("=" * 80)
    print("BACKFILL DRY-RUN COMPLETE")
    print("=" * 80)
    print(f"Articles checked: {total_checked:,}")
    print(f"Wire detected: {total_wire:,} ({100.0 * total_wire / total_checked:.2f}%)")
    print(f"Output: {output_csv}")
    print()


if __name__ == "__main__":
    main()
