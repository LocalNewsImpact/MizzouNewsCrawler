from src.models.database import DatabaseManager
from sqlalchemy import text
from datetime import datetime, timedelta
import csv
import sys
import time
import argparse


def classify(d7: int, e7: int, td14: int, ex14: int, rate14: float):
    health = "Healthy"
    detail = ""
    if ex14 == 0 and td14 == 0:
        health, detail = "No Activity", "No discoveries or extractions in 14 days"
    elif e7 == 0 and td14 > 0:
        health, detail = "Extraction Issue", "No extractions in past 7 days"
    elif d7 == 0 and td14 > 0:
        health, detail = "Discovery Issue", "No recent discoveries (7d)"
    elif td14 > 0 and ex14 > 0 and rate14 < 25.0:
        health, detail = "Warning", "Low extraction success rate (<25%)"
    return health, detail


def main():
    parser = argparse.ArgumentParser(description="Generate legacy CSV for all sources in batches")
    parser.add_argument("--batch-size", type=int, default=200, help="Number of sources per batch")
    parser.add_argument("--sleep-sec", type=float, default=0.25, help="Sleep between batches to reduce DB load")
    args = parser.parse_args()

    db = DatabaseManager()
    now = datetime.utcnow()
    cut14 = now - timedelta(days=14)
    cut7 = now - timedelta(days=7)
    order_map = {
        "Extraction Issue": 0,
        "Discovery Issue": 1,
        "No Activity": 2,
        "Warning": 3,
        "Healthy": 4,
    }

    recs = []
    with db.get_session() as session:
        total_sources = session.execute(
            text("SELECT COUNT(*) FROM sources WHERE COALESCE(status, '') <> 'retired'")
        ).scalar() or 0
        print(
            f"Starting legacy CSV: total sources={total_sources}, batch_size={args.batch_size}",
            file=sys.stderr,
            flush=True,
        )
        offset = 0
        processed_total = 0
        while offset < total_sources:
            rows = session.execute(
                text(
                    "SELECT id, host, canonical_name, status FROM sources "
                    "WHERE COALESCE(status, '') <> 'retired' "
                    "ORDER BY canonical_name LIMIT :lim OFFSET :off"
                ),
                {"lim": args.batch_size, "off": offset},
            ).fetchall()
            # Process this batch
            for sid, host, cname, status in rows:
                disc = session.execute(
                    text(
                        "SELECT COUNT(CASE WHEN discovered_at >= :c14 THEN 1 END) AS d14, "
                        "COUNT(CASE WHEN discovered_at >= :c7 THEN 1 END) AS d7, "
                        "MAX(discovered_at) AS last_disc "
                        "FROM candidate_links WHERE source_id=:id"
                    ),
                    {"id": sid, "c14": cut14, "c7": cut7},
                ).fetchone() or (0, 0, None)
                ext = session.execute(
                    text(
                        "SELECT COUNT(CASE WHEN a.extracted_at >= :c14 THEN 1 END) AS e14, "
                        "COUNT(CASE WHEN a.extracted_at >= :c7 THEN 1 END) AS e7, "
                        "MAX(a.extracted_at) AS last_ext FROM articles a "
                        "JOIN candidate_links cl ON a.candidate_link_id=cl.id "
                        "WHERE cl.source_id=:id"
                    ),
                    {"id": sid, "c14": cut14, "c7": cut7},
                ).fetchone() or (0, 0, None)
                stages = session.execute(
                    text(
                        "SELECT COUNT(CASE WHEN a.status='extracted' AND a.extracted_at >= :c14 THEN 1 END) AS at_extracted, "
                        "COUNT(CASE WHEN a.status='cleaned' AND a.extracted_at >= :c14 THEN 1 END) AS at_cleaned, "
                        "COUNT(CASE WHEN a.status='labeled' AND a.extracted_at >= :c14 THEN 1 END) AS at_labeled "
                        "FROM articles a JOIN candidate_links cl ON a.candidate_link_id=cl.id WHERE cl.source_id=:id"
                    ),
                    {"id": sid, "c14": cut14},
                ).fetchone() or (0, 0, 0)

                td14 = disc[0] or 0
                d7 = disc[1] or 0
                ex14 = ext[0] or 0
                e7 = ext[1] or 0
                rate14 = round(100 * ex14 / (td14 or 1), 1) if td14 > 0 else 0
                health, detail = classify(d7, e7, td14, ex14, rate14)
                recs.append(
                    [
                        host or cname,
                        health,
                        detail,
                        status,
                        td14,
                        d7,
                        ex14,
                        e7,
                        rate14,
                        disc[2].isoformat() if disc[2] else "",
                        ext[2].isoformat() if ext[2] else "",
                        stages[0] or 0,
                        stages[1] or 0,
                        stages[2] or 0,
                    ]
                )
            processed_total += len(rows)
            print(
                f"Processed {processed_total}/{total_sources} sources...",
                file=sys.stderr,
                flush=True,
            )
            offset += args.batch_size
            if args.sleep_sec:
                time.sleep(args.sleep_sec)

    # Sort by health priority before ranking
    recs.sort(key=lambda r: order_map.get(r[1], 5))

    w = csv.writer(sys.stdout)
    w.writerow(
        [
            "Rank",
            "Hostname",
            "Health Status",
            "Issue Details",
            "Source Status",
            "Discovered (14d)",
            "Discovered (7d)",
            "Extracted (14d)",
            "Extracted (7d)",
            "Extraction Success Rate (%)",
            "Last Discovery",
            "Last Extraction",
            "Articles at Extracted",
            "Articles at Cleaned",
            "Articles at Labeled",
        ]
    )
    for i, r in enumerate(recs, 1):
        w.writerow([i] + r)
    print("Completed legacy CSV generation.", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
