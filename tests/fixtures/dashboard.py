from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.telemetry.store import TelemetryStore
from src.utils.comprehensive_telemetry import ComprehensiveExtractionTelemetry


@dataclass
class DashboardTelemetryFixture:
    """Seeded telemetry helper for dashboard tests."""

    db_path: Path
    csv_path: Path
    store: TelemetryStore

    def flush(self) -> None:
        """Flush any pending telemetry writes and shut the queue down."""

        if self.store.async_writes:
            self.store.flush()
        # Always stop the worker thread so repeated tests don't leak threads.
        self.store.shutdown(wait=True)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


def seed_dashboard_telemetry(
    tmp_path: Path,
    *,
    async_writes: bool = True,
) -> DashboardTelemetryFixture:
    """Create a seeded telemetry + UI database for dashboard tests.

    The fixture populates:
      * ``extraction_telemetry_v2`` with both success and failure rows.
      * ``http_error_summary`` with HTTP error aggregates used by alerts.
      * ``candidates``/``snapshots``/``dedupe_audit`` for UI overview stats.
      * A small CSV for ``/api/ui_overview`` total/wire counts.
    """

    db_path = tmp_path / "dashboard_telemetry.db"
    csv_path = tmp_path / "articles.csv"

    store = TelemetryStore(
        database=f"sqlite:///{db_path}",
        async_writes=async_writes,
    )
    # Ensure telemetry tables exist by instantiating with the seeded store.
    ComprehensiveExtractionTelemetry(store=store)

    _seed_extraction_tables(store)
    _seed_dashboard_tables(db_path)
    _seed_articles_csv(csv_path)

    return DashboardTelemetryFixture(
        db_path=db_path,
        csv_path=csv_path,
        store=store,
    )


def _seed_extraction_tables(store: TelemetryStore) -> None:
    """Populate extraction telemetry tables with deterministic data."""

    now = datetime.utcnow()
    earlier = now - timedelta(hours=6)

    rows = [
        {
            "operation_id": "op-success",
            "article_id": "article-success",
            "url": "https://healthy.local/article",
            "publisher": "Healthy Local",
            "host": "healthy.local",
            "http_status_code": 200,
            "http_error_type": None,
            "methods_attempted": ["rss", "newspaper4k"],
            "successful_method": "newspaper4k",
            "method_success": {"rss": False, "newspaper4k": True},
            "method_errors": {"rss": "timeout"},
            "field_extraction": {
                "rss": {
                    "title": False,
                    "content": False,
                    "publish_date": False,
                    "author": False,
                },
                "newspaper4k": {
                    "title": True,
                    "content": True,
                    "publish_date": True,
                    "author": True,
                },
            },
            "extracted_fields": {
                "title": True,
                "author": True,
                "content": True,
                "publish_date": True,
            },
            "final_field_attribution": {
                "title": "newspaper4k",
                "content": "newspaper4k",
            },
            "alternative_extractions": {},
            "content_length": 1024,
            "is_success": 1,
            "error_message": None,
            "error_type": None,
            "start_time": earlier,
            "end_time": now,
            "total_duration_ms": 1800.0,
            "response_size_bytes": 20480,
            "response_time_ms": 320.0,
        },
        {
            "operation_id": "op-http-fail",
            "article_id": "article-fail",
            "url": "https://blocked.local/article",
            "publisher": "Blocked Local",
            "host": "blocked.local",
            "http_status_code": 503,
            "http_error_type": "5xx_server_error",
            "methods_attempted": ["rss"],
            "successful_method": None,
            "method_success": {"rss": False},
            "method_errors": {"rss": "HTTP 503"},
            "field_extraction": {
                "rss": {
                    "title": False,
                    "content": False,
                    "publish_date": False,
                    "author": False,
                },
            },
            "extracted_fields": {
                "title": False,
                "author": False,
                "content": False,
                "publish_date": False,
            },
            "final_field_attribution": {},
            "alternative_extractions": {},
            "content_length": 0,
            "is_success": 0,
            "error_message": "HTTP 503",
            "error_type": "http_error",
            "start_time": earlier,
            "end_time": now - timedelta(minutes=30),
            "total_duration_ms": 4200.0,
            "response_size_bytes": 0,
            "response_time_ms": 1000.0,
        },
        {
            "operation_id": "op-verification-fail",
            "article_id": "article-verification",
            "url": "https://verification.local/article",
            "publisher": "Verification Local",
            "host": "verification.local",
            "http_status_code": 429,
            "http_error_type": "4xx_client_error",
            "methods_attempted": ["rss", "newspaper4k"],
            "successful_method": None,
            "method_success": {"rss": False, "newspaper4k": False},
            "method_errors": {
                "rss": "HTTP 429",
                "newspaper4k": "verification failed",
            },
            "field_extraction": {
                "rss": {
                    "title": False,
                    "content": False,
                    "publish_date": False,
                    "author": False,
                },
                "newspaper4k": {
                    "title": False,
                    "content": False,
                    "publish_date": False,
                    "author": False,
                },
            },
            "extracted_fields": {
                "title": False,
                "author": False,
                "content": False,
                "publish_date": False,
            },
            "final_field_attribution": {},
            "alternative_extractions": {},
            "content_length": 0,
            "is_success": 0,
            "error_message": "verification failure",
            "error_type": "verification",
            "start_time": earlier,
            "end_time": now - timedelta(minutes=15),
            "total_duration_ms": 2400.0,
            "response_size_bytes": 0,
            "response_time_ms": 850.0,
        },
    ]

    http_summary = [
        (
            "blocked.local",
            503,
            "5xx_server_error",
            3,
            now - timedelta(days=1),
            now,
        ),
        (
            "verification.local",
            429,
            "4xx_client_error",
            2,
            now - timedelta(hours=3),
            now - timedelta(minutes=5),
        ),
    ]

    detection_rows = [
        (
            "article-detect",
            "op-detect",
            "https://healthy.local/detect",
            "Healthy Local",
            "healthy.local",
            "opinion",
            "high",
            0.92,
            "matched_signals",
            json.dumps({"title": ["opinion"]}),
            "v1",
            now.isoformat(),
        )
    ]

    with store.connection() as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO extraction_telemetry_v2 (
                    operation_id, article_id, url, publisher, host,
                    start_time, end_time, total_duration_ms,
                    http_status_code, http_error_type,
                    response_size_bytes, response_time_ms,
                    methods_attempted, successful_method,
                    method_timings, method_success, method_errors,
                    field_extraction, extracted_fields,
                    final_field_attribution, alternative_extractions,
                    content_length, is_success, error_message, error_type
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    row["operation_id"],
                    row["article_id"],
                    row["url"],
                    row["publisher"],
                    row["host"],
                    row["start_time"],
                    row["end_time"],
                    row["total_duration_ms"],
                    row["http_status_code"],
                    row["http_error_type"],
                    row["response_size_bytes"],
                    row["response_time_ms"],
                    json.dumps(row["methods_attempted"]),
                    row["successful_method"],
                    json.dumps({}),
                    json.dumps(row["method_success"]),
                    json.dumps(row["method_errors"]),
                    json.dumps(row["field_extraction"]),
                    json.dumps(row["extracted_fields"]),
                    json.dumps(row["final_field_attribution"]),
                    json.dumps(row["alternative_extractions"]),
                    row["content_length"],
                    row["is_success"],
                    row["error_message"],
                    row["error_type"],
                ),
            )

        conn.executemany(
            """
            INSERT INTO http_error_summary (
                host, status_code, error_type, count, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(host, status_code) DO UPDATE SET
                count = excluded.count,
                last_seen = excluded.last_seen
            """,
            http_summary,
        )

        conn.executemany(
            """
            INSERT INTO content_type_detection_telemetry (
                article_id, operation_id, url, publisher, host,
                status, confidence, confidence_score, reason,
                evidence, version, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            detection_rows,
        )

        conn.commit()


def _seed_dashboard_tables(db_path: Path) -> None:
    """Populate UI tables used by the dashboard APIs."""

    conn = sqlite3.connect(db_path)
    try:
        _create_dashboard_tables(conn)
        now = datetime.utcnow().isoformat()

        snapshots = [
                (
                    "snap-1",
                    "broken.local",
                    None,
                ),
                (
                    "snap-2",
                    "broken.local",
                    None,
                ),
                (
                    "snap-3",
                    "healthy.local",
                    now,
                ),
        ]
        candidates = [
                (
                    "cand-1",
                    "snap-1",
                    "meta.title",
                    "title",
                    0.2,
                    120,
                    None,
                    None,
                    0,
                    now,
                ),
                (
                    "cand-2",
                    "snap-1",
                    "meta.description",
                    "description",
                    0.8,
                    200,
                    None,
                    None,
                    0,
                    now,
                ),
                (
                    "cand-3",
                    "snap-2",
                    "meta.author",
                    "author",
                    0.5,
                    80,
                    None,
                    None,
                    1,
                    now,
                ),
        ]
        dedupe = [
                (
                    "art-1",
                    "art-dup",
                    "broken.local",
                    0.91,
                    0,
                    now,
                ),
                (
                    "art-2",
                    "art-dup2",
                    "healthy.local",
                    0.65,
                    1,
                    now,
                ),
        ]

        conn.executemany(
                """
                INSERT OR REPLACE INTO snapshots (id, host, reviewed_at)
                VALUES (?, ?, ?)
                """,
                snapshots,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO candidates (
                id, snapshot_id, selector, field, score, words, snippet, alts,
                accepted, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            candidates,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO dedupe_audit (
                article_uid, neighbor_uid, host,
                similarity, dedupe_flag, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            dedupe,
        )

        conn.commit()
    finally:
        conn.close()


def _create_dashboard_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            host TEXT NOT NULL,
            reviewed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            snapshot_id TEXT,
            selector TEXT,
            field TEXT,
            score REAL,
            words INTEGER,
            snippet TEXT,
            alts TEXT,
            accepted INTEGER,
            created_at TEXT
        )
        """,
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dedupe_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_uid TEXT,
            neighbor_uid TEXT,
            host TEXT,
            similarity REAL,
            dedupe_flag INTEGER,
            created_at TEXT
        )
        """
    )
    conn.commit()


def _seed_articles_csv(csv_path: Path) -> None:
    csv_path.write_text("wire\n1\n0\n", encoding="utf-8")
