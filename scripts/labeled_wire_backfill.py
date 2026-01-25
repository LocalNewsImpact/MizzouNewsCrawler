#!/usr/bin/env python3
"""
Dry-run backfill to identify labeled articles that should be wire.
Uses the same pattern as backfill_wire_status.py but targets labeled articles.
"""

import csv
from datetime import datetime

from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text


def main():
    db = DatabaseManager()
    detector = ContentTypeDetector()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"labeled_wire_backfill_{timestamp}.csv"
    log_file = f"labeled_wire_backfill_{timestamp}.log"

    print(f"Wire Detection Dry-Run for Labeled Articles")
    print(f"=" * 80)
    print(f"Output CSV: {output_file}")
    print(f"Log file: {log_file}")
    print()

    total_processed = 0
    total_wire_detected = 0
    wire_articles = []
    batch_size = 1000

    with open(log_file, "w") as log:
        log.write(f"Labeled Articles Wire Detection - {timestamp}\n")
        log.write("=" * 80 + "\n\n")

        with db.get_session() as session:
            # Get total count
            total_count = session.execute(text("""
                SELECT COUNT(*)
                FROM articles
                WHERE status = 'labeled' AND wire_check_status = 'complete'
            """)).scalar()

            print(f"Total labeled articles: {total_count:,}")
            log.write(f"Total labeled articles: {total_count:,}\n\n")

            offset = 0

            while offset < total_count:
                # Get batch
                results = session.execute(text("""
                    SELECT
                        a.id,
                        a.url,
                        a.title,
                        a.author,
                        a.text,
                        cl.source
                    FROM articles a
                    LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id
                    WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
                    ORDER BY a.id
                    LIMIT :batch_size OFFSET :offset
                """), {"batch_size": batch_size, "offset": offset}).fetchall()

                if not results:
                    break

                batch_wire = 0

                for row in results:
                    total_processed += 1
                    article_id, url, title, author, article_text, source = row

                    # Run wire detection
                    result = detector._detect_wire_service(
                        url=url,
                        content=article_text or title or "",
                        metadata={"author": author}
                    )

                    if result and result.status == "wire":
                        total_wire_detected += 1
                        batch_wire += 1

                        services = result.evidence.get("detected_services", [])
                        service = services[0] if services else "Unknown"
                        tier = result.evidence.get("detection_tier", "unknown")

                        wire_articles.append({
                            "article_id": article_id,
                            "url": url,
                            "title": (title or "")[:150],
                            "author": author or "",
                            "source": source or "",
                            "detected_service": service,
                            "detection_tier": tier,
                            "confidence": result.confidence,
                        })

                offset += batch_size

                # Progress
                pct = 100.0 * offset / total_count
                msg = f"Progress: {offset:,}/{total_count:,} ({pct:.1f}%) | Batch wire: {batch_wire} | Total: {total_wire_detected:,}"
                print(msg)
                log.write(msg + "\n")
                log.flush()

        # Summary
        wire_pct = 100.0 * total_wire_detected / total_processed if total_processed else 0
        summary = f"\n{'=' * 80}\n"
        summary += f"RESULTS\n"
        summary += f"{'=' * 80}\n"
        summary += f"Total processed: {total_processed:,}\n"
        summary += f"Wire detected: {total_wire_detected:,} ({wire_pct:.2f}%)\n"
        summary += f"Output: {output_file}\n"

        print(summary)
        log.write(summary)

    # Write CSV
    if wire_articles:
        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=wire_articles[0].keys())
            writer.writeheader()
            writer.writerows(wire_articles)
        print(f"\nWrote {len(wire_articles):,} wire articles to {output_file}")
    else:
        print("\nNo wire articles detected")


if __name__ == "__main__":
    main()
