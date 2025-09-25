#!/usr/bin/env python3
"""Export removable boilerplate segments and wire-service patterns."""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# Ensure src directory is importable
IMPORT_ROOT = Path(__file__).parent / "src"
if str(IMPORT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(IMPORT_ROOT))

# Local imports (after sys.path adjustment)
from utils.content_cleaner_balanced import (  # type: ignore  # noqa: E402
    BalancedBoundaryContentCleaner,
)


DB_PATH = Path("data/mizzou.db")
DEFAULT_OUTPUT_DIR = Path("reports")


def get_domain_article_counts(
    db_path: Path,
    min_length: int = 100,
) -> Dict[str, int]:
    """Return article counts grouped by domain for eligible content."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT url
        FROM articles
        WHERE content IS NOT NULL
          AND content != ''
          AND LENGTH(content) > ?
        """,
        (min_length,),
    )

    counts: Dict[str, int] = {}
    for (url,) in cursor.fetchall():
        domain = extract_domain(url)
        if not domain or domain == "unknown":
            continue
        counts[domain] = counts.get(domain, 0) + 1

    conn.close()
    return counts


def extract_domain(url: str) -> str:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return "unknown"


def detect_wire_pattern(
    cleaner: BalancedBoundaryContentCleaner,
    text: str,
    domain: str,
) -> Any:
    """Use cleaner's wire detection helper on a segment."""
    try:
        # pylint: disable=protected-access
        return cleaner._detect_wire_service_in_pattern(
            text,
            domain,
        )
    except Exception:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export removable segments (full text) and wire patterns",
    )
    parser.add_argument(
        "--max-domains",
        type=int,
        default=5,
        help="Maximum number of domains to analyze",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Sample size per domain for analysis",
    )
    parser.add_argument(
        "--min-articles",
        type=int,
        default=3,
        help="Minimum number of articles per domain before analysis",
    )
    parser.add_argument(
        "--min-boundary-score",
        type=float,
        default=0.5,
        help="Minimum boundary score to include a segment in the export",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path for JSON output; defaults to "
            "reports/cleaning_segments_<timestamp>.json"
        ),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DB_PATH,
        help="Path to SQLite database (default: data/mizzou.db)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.db_path.exists():
        parser.error(f"Database not found at {args.db_path}")

    output_path = args.output
    if output_path is None:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = (
            DEFAULT_OUTPUT_DIR / f"cleaning_segments_{timestamp}.json"
        )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    domain_counts = get_domain_article_counts(args.db_path)
    eligible_domains = {
        domain: count
        for domain, count in domain_counts.items()
        if count >= args.min_articles
    }

    if not eligible_domains:
        parser.error("No domains with sufficient article counts found.")

    sorted_domains = sorted(
        eligible_domains.items(), key=lambda item: item[1], reverse=True
    )[: args.max_domains]

    cleaner = BalancedBoundaryContentCleaner(
        db_path=str(args.db_path),
        enable_telemetry=False,
    )

    export_payload: Dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat(),
        "parameters": {
            "max_domains": args.max_domains,
            "sample_size": args.sample_size,
            "min_articles": args.min_articles,
            "min_boundary_score": args.min_boundary_score,
            "db_path": str(args.db_path),
        },
        "domains": [],
    }

    print("🧾 Exporting removable segments and wire patterns\n")

    for index, (domain, count) in enumerate(sorted_domains, 1):
        print(f"{index:2d}. {domain} (articles: {count})")
        analysis = cleaner.analyze_domain(
            domain,
            sample_size=args.sample_size,
            min_occurrences=args.min_articles,
        )

        segments: List[Dict[str, Any]] = []
        wire_patterns: List[Dict[str, Any]] = []

        for seg_index, segment in enumerate(analysis.get("segments", []), 1):
            boundary_score = segment.get("boundary_score", 0.0)
            if boundary_score < args.min_boundary_score:
                continue

            wire_info = detect_wire_pattern(
                cleaner,
                segment.get("text", ""),
                domain,
            )
            if wire_info:
                wire_entry = {
                    "segment_index": seg_index,
                    "provider": wire_info.get("provider"),
                    "detection_method": wire_info.get("detection_method"),
                    "confidence": wire_info.get("confidence"),
                    "pattern_text": segment.get("text", ""),
                }
                wire_patterns.append(wire_entry)

            segments.append(
                {
                    "segment_index": seg_index,
                    "text": segment.get("text", ""),
                    "pattern_type": segment.get("pattern_type"),
                    "boundary_score": boundary_score,
                    "occurrences": segment.get("occurrences"),
                    "length": segment.get("length"),
                    "position_consistency": segment.get(
                        "position_consistency"
                    ),
                    "removal_reason": segment.get("removal_reason"),
                    "article_ids": segment.get("article_ids", []),
                }
            )

        stats = analysis.get("stats", {})
        export_payload["domains"].append(
            {
                "domain": domain,
                "total_articles": count,
                "analyzed_articles": analysis.get("article_count", 0),
                "removal_percentage": stats.get("removal_percentage"),
                "removable_characters": stats.get("total_removable_chars"),
                "segment_count": len(segments),
                "segments": segments,
                "wire_patterns": wire_patterns,
            }
        )

        if segments:
            print(
                f"   Segments exported: {len(segments)} | "
                f"Estimated removal: {stats.get('removal_percentage', 0):.1f}%"
            )
        else:
            print("   No segments met the boundary score threshold")

        if wire_patterns:
            providers = {entry.get("provider") for entry in wire_patterns}
            provider_list = ", ".join(sorted(filter(None, providers)))
            print(f"   Wire-service patterns: {provider_list or 'detected'}")

        print()

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(export_payload, handle, indent=2, ensure_ascii=False)

    print(f"✅ Export complete: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
