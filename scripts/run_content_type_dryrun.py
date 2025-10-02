"""Run the content-type detector against stored articles and export matches.

This utility performs a dry run of the opinion/obituary heuristics using the
existing article corpus in the SQLite database. The output is written to a CSV
in the reports directory so analysts can review high-signal detections without
mutating article status or telemetry tables.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.content_type_detector import ContentTypeDetector

DEFAULT_DB_PATH = Path("data/mizzou.db")
DEFAULT_OUTPUT_DIR = Path("reports")


def _normalize_keywords(raw_keywords: Any) -> str:
    if not raw_keywords:
        return ""
    if isinstance(raw_keywords, str):
        return raw_keywords
    if isinstance(raw_keywords, Iterable):
        return "; ".join(str(item) for item in raw_keywords if item)
    return str(raw_keywords)


def _load_articles(
    connection: sqlite3.Connection, limit: int | None = None
):
    query = (
        "SELECT a.id, a.candidate_link_id, a.url, a.title, a.content, "
        "a.metadata, a.publish_date, cl.source, cl.source_name, "
        "cl.source_city, cl.source_county, cl.owner "
        "FROM articles a "
        "LEFT JOIN candidate_links cl ON cl.id = a.candidate_link_id "
        "WHERE a.content IS NOT NULL AND a.content != ''"
    )
    params: list[Any] = []
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    cursor = connection.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _flatten_evidence(evidence: dict[str, list[str]]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, values in evidence.items():
        if not values:
            continue
        flattened[f"evidence_{key}"] = "; ".join(values)
    return flattened


def run_dry_run(
    *,
    database: Path,
    output_dir: Path,
    limit: int | None,
    min_score: float | None,
) -> Path | None:
    detector = ContentTypeDetector()
    connection = sqlite3.connect(str(database))
    try:
        rows = _load_articles(connection, limit=limit)
    finally:
        connection.close()

    detections: list[dict[str, Any]] = []

    for (
        article_id,
        candidate_link_id,
        url,
        title,
        content,
        metadata_json,
        publish_date,
        source,
        source_name,
        source_city,
        source_county,
        owner,
    ) in rows:
        metadata: dict[str, Any] = {}
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                # Leave metadata empty when JSON is invalid
                pass

        result = detector.detect(
            url=url or "",
            title=title,
            metadata=metadata,
            content=content,
        )
        if not result:
            continue

        if result.status not in {"opinion", "obituary"}:
            continue

        if min_score is not None and result.confidence_score < min_score:
            continue

        detected_at = datetime.utcnow().replace(microsecond=0).isoformat()

        record: dict[str, Any] = {
            "article_id": article_id,
            "candidate_link_id": candidate_link_id,
            "url": url,
            "title": title,
            "status": result.status,
            "confidence": result.confidence,
            "confidence_score": result.confidence_score,
            "reason": result.reason,
            "detected_at": detected_at,
            "detector_version": result.detector_version,
            "source": source,
            "source_name": source_name,
            "source_city": source_city,
            "source_county": source_county,
            "owner": owner,
            "publish_date": publish_date,
            "metadata_section": metadata.get("section"),
            "metadata_subsection": metadata.get("subsection"),
            "metadata_keywords": _normalize_keywords(metadata.get("keywords")),
        }
        record.update(_flatten_evidence(result.evidence))
        record["evidence_json"] = json.dumps(
            result.evidence,
            ensure_ascii=False,
        )
        detections.append(record)

    if not detections:
        return None

    df = pd.DataFrame(detections)
    df.sort_values(
        by=["status", "confidence_score", "source_name", "publish_date"],
        ascending=[True, False, True, True],
        inplace=True,
        ignore_index=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"content_type_dryrun_{timestamp}.csv"
    df.to_csv(output_path, index=False)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=(
            "Path to the SQLite database containing articles "
            "(default: data/mizzou.db)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Directory where the CSV export will be written "
            "(default: reports/)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional limit on the number of articles to evaluate",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        help=(
            "Only include detections with a confidence score at or above "
            "this value"
        ),
    )
    args = parser.parse_args()

    output_path = run_dry_run(
        database=args.database,
        output_dir=args.output_dir,
        limit=args.limit,
        min_score=args.min_score,
    )

    if output_path is None:
        print("No opinion or obituary detections found; no CSV written.")
    else:
        print(f"Exported detections to {output_path}")


if __name__ == "__main__":
    main()
