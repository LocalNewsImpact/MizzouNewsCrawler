"""Apply content-type detector results back into the production database.

This script evaluates all stored articles using the heuristic
`ContentTypeDetector`, updates the `articles` table with the detection payload,
and records a telemetry row for each detection.

It is intentionally idempotent for a given `--operation-id`: prior telemetry
rows for the same article are deleted before inserting the new record. Articles
that do not trigger an opinion/obituary classification are left untouched.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.utils.content_type_detector import ContentTypeDetector

DEFAULT_DB_PATH = Path("data/mizzou.db")


def _normalize_keywords(raw_keywords: Any) -> str:
    if not raw_keywords:
        return ""
    if isinstance(raw_keywords, str):
        return raw_keywords
    if isinstance(raw_keywords, Iterable):
        return "; ".join(str(item) for item in raw_keywords if item)
    return str(raw_keywords)


def _load_articles(
    connection: sqlite3.Connection,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    query = (
        "SELECT a.id, a.url, a.title, a.content, a.metadata, a.status, "
        "a.candidate_link_id, cl.source, cl.source_name, cl.source_city, "
        "cl.source_county, cl.owner "
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


def _prepare_detection_payload(
    *,
    result,
) -> dict[str, Any]:
    detected_at = datetime.utcnow().replace(microsecond=0).isoformat()
    return {
        "status": result.status,
        "confidence": result.confidence,
        "confidence_score": result.confidence_score,
        "reason": result.reason,
        "evidence": result.evidence,
        "version": result.detector_version,
        "detected_at": detected_at,
    }


def _update_article(
    connection: sqlite3.Connection,
    *,
    article_id: str,
    new_status: str,
    metadata_payload: dict[str, Any],
) -> None:
    metadata_json = json.dumps(metadata_payload, ensure_ascii=False)
    connection.execute(
        "UPDATE articles SET status = ?, metadata = ? WHERE id = ?",
        (new_status, metadata_json, article_id),
    )


def _write_telemetry(
    connection: sqlite3.Connection,
    *,
    article_id: str,
    candidate_link_id: str | None,
    url: str,
    publisher: str | None,
    host: str,
    detection_payload: dict[str, Any],
    operation_id: str,
) -> None:
    evidence_json = json.dumps(
        detection_payload.get("evidence"),
        ensure_ascii=False,
    )

    connection.execute(
        "DELETE FROM content_type_detection_telemetry WHERE article_id = ?",
        (article_id,),
    )

    connection.execute(
        """
        INSERT INTO content_type_detection_telemetry (
            article_id, operation_id, url, publisher, host,
            status, confidence, confidence_score, reason,
            evidence, version, detected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article_id,
            operation_id,
            url,
            publisher,
            host,
            detection_payload["status"],
            detection_payload["confidence"],
            detection_payload["confidence_score"],
            detection_payload["reason"],
            evidence_json,
            detection_payload["version"],
            detection_payload["detected_at"],
        ),
    )


def apply_detections(
    *,
    database: Path,
    limit: int | None,
    min_score: float | None,
    operation_id: str,
) -> tuple[int, int]:
    detector = ContentTypeDetector()

    connection = sqlite3.connect(str(database))
    connection.row_factory = sqlite3.Row

    try:
        rows = _load_articles(connection, limit)

        updated_count = 0
        telemetry_count = 0

        for row in rows:
            article_id = row["id"]
            url = row["url"] or ""
            title = row["title"]
            content = row["content"]
            metadata_json = row["metadata"]

            metadata: dict[str, Any] = {}
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json)
                except json.JSONDecodeError:
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}

            result = detector.detect(
                url=url,
                title=title,
                metadata=metadata,
                content=content,
            )

            if not result or result.status not in {"opinion", "obituary"}:
                continue

            if min_score is not None and result.confidence_score < min_score:
                continue

            detection_payload = _prepare_detection_payload(result=result)
            metadata["content_type_detection"] = detection_payload

            host = urlparse(url).netloc
            publisher = row["source_name"] or row["source"]

            with connection:
                _update_article(
                    connection,
                    article_id=article_id,
                    new_status=result.status,
                    metadata_payload=metadata,
                )
                _write_telemetry(
                    connection,
                    article_id=article_id,
                    candidate_link_id=row["candidate_link_id"],
                    url=url,
                    publisher=publisher,
                    host=host,
                    detection_payload=detection_payload,
                    operation_id=operation_id,
                )

            updated_count += 1
            telemetry_count += 1

        return updated_count, telemetry_count
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=(
            "Path to the SQLite database containing articles (default: data/mizzou.db)"
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
        help=("Only include detections with a confidence score at or above this value"),
    )
    parser.add_argument(
        "--operation-id",
        type=str,
        default=(
            f"content-type-backfill-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        ),
        help="Identifier stored with telemetry rows to track this execution",
    )
    args = parser.parse_args()

    updated, telemetry_rows = apply_detections(
        database=args.database,
        limit=args.limit,
        min_score=args.min_score,
        operation_id=args.operation_id,
    )

    print(
        f"Updated {updated} articles and wrote {telemetry_rows} telemetry rows "
        f"using operation_id={args.operation_id}"
    )


if __name__ == "__main__":
    main()
