#!/usr/bin/env python3
"""Scan articles in production (or configured DB) for wire content using ContentTypeDetector

This script connects to the database and runs the detector on a sample or the
entire set of non-wire articles. It outputs a CSV of articles the detector
would mark as wire. Designed for dry-run analysis only.

Usage:
    python scripts/scan_production_with_new_detector.py --limit 100 --output /tmp/wire.csv
    python scripts/scan_production_with_new_detector.py --status labeled --limit 100
"""

import argparse
import csv
import sys
from pathlib import Path

from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text


def map_detection_to_service(detection):
    """Return a canonical short label for the detected wire service.

    This function centralizes the CSV mapping logic and makes unit testing
    easier. It intentionally avoids treating Kansas Reflector and WAVE as
    syndicated evidence unless the detector explicitly reports States
    Newsroom or another syndicated wire.
    """
    ev = detection.evidence or {}
    service = "Unknown"

    # Prefer the detector's explicit list of detected_services when available
    if "detected_services" in ev and ev["detected_services"]:
        detected_services_list = ev["detected_services"]
        primary = detected_services_list[0]
        service_map = {
            "Associated Press": "AP",
            "The Associated Press": "AP",
            "AFP": "AFP",
            "Reuters": "Reuters",
            "CNN": "CNN",
            "Bloomberg": "Bloomberg",
            "NPR": "NPR",
            "PBS": "PBS",
            "USA TODAY": "USA TODAY",
            "The Missouri Independent": "The Missouri Independent",
            "States Newsroom": "States Newsroom",
        }
        service = service_map.get(primary, primary)

        # If the only evidence for States Newsroom is an affiliate like Kansas Reflector,
        # do not report it as a syndicated wire.
        if service == "States Newsroom":
            evidence_text = ""
            if "author" in ev and ev["author"]:
                author_text = (
                    "; ".join(ev["author"]) if isinstance(ev["author"], list) else str(ev["author"])
                )
                evidence_text += author_text
            if "content" in ev and ev["content"]:
                content_text = (
                    "; ".join(ev["content"]) if isinstance(ev["content"], list) else str(ev["content"])
                )
                evidence_text += " " + content_text
            evidence_text_lower = evidence_text.lower()
            if (
                "states news" not in evidence_text_lower
                and (
                    "kansas reflector" in evidence_text_lower
                    or "kansasreflector" in evidence_text_lower
                )
            ):
                service = "Unknown"

        # WAVE is a single newsroom; do not report as a syndicated wire
        if service == "WAVE":
            service = "Unknown"
        return service

    # Fallback to scanning the evidence text for a match if the detector did not supply
    # a normalized service list (older detectors or edge cases)
    if "author" in ev and ev["author"]:
        evidence_str = (
            "; ".join(ev["author"]) if isinstance(ev["author"], list) else str(ev["author"])
        )
        if "AFP" in evidence_str:
            return "AFP"
        if "Associated Press" in evidence_str or "AP" in evidence_str:
            return "AP"
        if "Reuters" in evidence_str:
            return "Reuters"
        if "CNN" in evidence_str:
            return "CNN"
        if "USA TODAY" in evidence_str or "USA Today" in evidence_str:
            return "USA TODAY"
        if "States Newsroom" in evidence_str:
            return "States Newsroom"

    if "content" in ev and ev["content"]:
        evidence_str = (
            "; ".join(ev["content"]) if isinstance(ev["content"], list) else str(ev["content"])
        )
        if "AFP" in evidence_str:
            return "AFP"
        if "Associated Press" in evidence_str or "AP" in evidence_str:
            return "AP"
        if "Reuters" in evidence_str:
            return "Reuters"
        if "States Newsroom" in evidence_str:
            return "States Newsroom"

    return service



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Limit number of articles to process")
    parser.add_argument(
        "--status",
        type=str,
        default="labeled",
        help="Article status to filter on (default: labeled)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path('/tmp/production_wire_scan.csv'),
        help="CSV output path",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional DATABASE_URL to override configured DatabaseManager",
    )
    args = parser.parse_args()

    db = DatabaseManager(database_url=args.db_url)
    detector = ContentTypeDetector()

    print(f"Detector version: {detector.VERSION}")
    print("Using Database URL: (masked)")

    with db.get_session() as session:
        limit_clause = f"LIMIT {args.limit}" if args.limit else ""
        columns = (
            "a.id, a.url, a.title, a.content, a.author, a.status"
        )
        query = text(
            f"SELECT {columns} FROM articles a "
            "WHERE a.status = :status AND a.content IS NOT NULL "
            "AND a.content != '' ORDER BY a.publish_date DESC "
            f"{limit_clause}"
        )
        result = session.execute(query, {"status": args.status})
        rows = list(result)
        print(f"Found {len(rows)} articles to check")

        # CSV header
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "id",
                "url",
                "author",
                "title",
                "current_status",
                "detected_status",
                "wire_service",
                "confidence",
                "reason",
                "evidence",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            detected = 0
            for (article_id, url, title, content, author, status) in rows:
                metadata = {"byline": author} if author else None
                detection = detector.detect(
                    url=url or "",
                    title=title,
                    metadata=metadata,
                    content=content or '',
                )
                if detection and detection.status == 'wire':
                    detected += 1
                    service = map_detection_to_service(detection)

                    writer.writerow({
                        "id": article_id,
                        "url": url or "",
                        "author": author or "",
                        "title": title or "",
                        "current_status": status,
                        "detected_status": detection.status,
                        "wire_service": service,
                        "confidence": detection.confidence,
                        "reason": detection.reason,
                        "evidence": str(detection.evidence),
                    })

    print(f"Detected {detected}/{len(rows)} as wire; CSV written to: {args.output}")


if __name__ == "__main__":
    sys.exit(main())

