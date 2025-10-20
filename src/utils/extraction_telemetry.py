"""Extraction telemetry writer backed by the shared ``TelemetryStore``."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from src.config import DATABASE_URL
from src.telemetry.store import TelemetryStore, get_store

from .extraction_outcomes import ExtractionResult

_EXTRACTION_OUTCOMES_DDL = """
CREATE TABLE IF NOT EXISTS extraction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL,
    article_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    outcome TEXT NOT NULL,
    extraction_time_ms REAL NOT NULL DEFAULT 0.0,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    http_status_code INTEGER,
    response_size_bytes INTEGER,
    has_title BOOLEAN NOT NULL DEFAULT 0,
    has_content BOOLEAN NOT NULL DEFAULT 0,
    has_author BOOLEAN NOT NULL DEFAULT 0,
    has_publish_date BOOLEAN NOT NULL DEFAULT 0,
    content_length INTEGER,
    title_length INTEGER,
    author_count INTEGER,
    content_quality_score REAL,
    error_message TEXT,
    error_type TEXT,
    is_success BOOLEAN NOT NULL DEFAULT 0,
    is_content_success BOOLEAN NOT NULL DEFAULT 0,
    is_technical_failure BOOLEAN NOT NULL DEFAULT 0,
    is_bot_protection BOOLEAN NOT NULL DEFAULT 0,
    metadata TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_EXTRACTION_OUTCOMES_INDEXES: Iterable[str] = (
    "CREATE INDEX IF NOT EXISTS idx_extraction_operation "
    "ON extraction_outcomes (operation_id)",
    "CREATE INDEX IF NOT EXISTS idx_extraction_article "
    "ON extraction_outcomes (article_id)",
    "CREATE INDEX IF NOT EXISTS idx_extraction_outcome "
    "ON extraction_outcomes (outcome)",
    "CREATE INDEX IF NOT EXISTS idx_extraction_success "
    "ON extraction_outcomes (is_success)",
    "CREATE INDEX IF NOT EXISTS idx_extraction_content_success "
    "ON extraction_outcomes (is_content_success)",
    "CREATE INDEX IF NOT EXISTS idx_extraction_timestamp "
    "ON extraction_outcomes (timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_extraction_url ON extraction_outcomes (url)",
    "CREATE INDEX IF NOT EXISTS idx_extraction_quality "
    "ON extraction_outcomes (content_quality_score)",
)


class ExtractionTelemetry:
    """Handles recording of extraction telemetry to the shared database."""

    def __init__(
        self,
        db_path: str | None = None,
        *,
        store: TelemetryStore | None = None,
        async_writes: bool | None = None,
    ) -> None:
        if store is not None:
            self._store = store
        else:
            if db_path is None:
                # Use DatabaseManager's engine if available (for Cloud SQL)
                try:
                    from src.models.database import DatabaseManager
                    db = DatabaseManager()
                    self._store = get_store(DATABASE_URL, engine=db.engine)
                except Exception:
                    # Fallback to creating own connection
                    self._store = get_store(DATABASE_URL)
            else:
                resolved = Path(db_path)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                async_flag = async_writes if async_writes is not None else False
                self._store = TelemetryStore(
                    database=f"sqlite:///{resolved}",
                    async_writes=async_flag,
                )

        self._ensure_statements = [
            _EXTRACTION_OUTCOMES_DDL,
            *_EXTRACTION_OUTCOMES_INDEXES,
        ]

    def flush(self) -> None:
        """Flush any pending asynchronous writes."""

        self._store.flush()

    # ------------------------------------------------------------------
    # write API
    # ------------------------------------------------------------------
    def record_extraction_outcome(
        self,
        operation_id: str,
        article_id: int,
        url: str,
        extraction_result: ExtractionResult,
    ) -> None:
        """Record detailed extraction outcome for reporting and analysis."""

        if not isinstance(extraction_result, ExtractionResult):
            msg = f"Warning: Expected ExtractionResult, got {type(extraction_result)}"
            print(msg)
            return

        metadata = extraction_result.extracted_content or {}
        metadata_json = json.dumps(metadata) if metadata else None

        title_issues = json.dumps(extraction_result.title_quality_issues or [])
        content_issues = json.dumps(extraction_result.content_quality_issues or [])
        author_issues = json.dumps(extraction_result.author_quality_issues or [])
        date_issues = json.dumps(extraction_result.publish_date_quality_issues or [])

        outcome_data = (
            operation_id,
            article_id,
            url,
            extraction_result.outcome.value,
            extraction_result.extraction_time_ms,
            extraction_result.start_time.isoformat(),
            extraction_result.end_time.isoformat(),
            extraction_result.http_status_code,
            extraction_result.response_size_bytes,
            int(extraction_result.has_title),
            int(extraction_result.has_content),
            int(extraction_result.has_author),
            int(extraction_result.has_publish_date),
            extraction_result.content_length,
            extraction_result.title_length,
            extraction_result.author_count,
            extraction_result.content_quality_score,
            extraction_result.error_message,
            extraction_result.error_type,
            int(extraction_result.is_success),
            int(extraction_result.is_content_success),
            int(extraction_result.is_technical_failure),
            int(extraction_result.is_bot_protection),
            metadata_json,
            title_issues,
            content_issues,
            author_issues,
            date_issues,
            extraction_result.overall_quality_score,
            int(bool(extraction_result.title_quality_issues)),
            int(bool(extraction_result.content_quality_issues)),
            int(bool(extraction_result.author_quality_issues)),
            int(bool(extraction_result.publish_date_quality_issues)),
        )

        insert_query = """
            INSERT INTO extraction_outcomes (
                operation_id, article_id, url, outcome,
                extraction_time_ms, start_time, end_time,
                http_status_code, response_size_bytes,
                has_title, has_content, has_author, has_publish_date,
                content_length, title_length, author_count,
                content_quality_score, error_message, error_type,
                is_success, is_content_success, is_technical_failure,
                is_bot_protection, metadata,
                title_quality_issues, content_quality_issues,
                author_quality_issues, publish_date_quality_issues,
                overall_quality_score, title_has_issues,
                content_has_issues, author_has_issues,
                publish_date_has_issues
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """

        status = "extracted" if extraction_result.is_success else "error"

        def writer(conn: sqlite3.Connection) -> None:
            conn.execute(insert_query, outcome_data)
            conn.execute(
                """
                UPDATE articles
                SET status = ?, processed_at = datetime('now')
                WHERE id = ?
                """,
                (status, article_id),
            )

        try:
            self._store.submit(writer, ensure=self._ensure_statements)
            outcome_value = extraction_result.outcome.value
            print(
                f"Recorded extraction outcome: {outcome_value} for article {article_id}"
            )
        except Exception as exc:
            print(f"Failed to record extraction outcome: {exc}")
            raise

    # ------------------------------------------------------------------
    # read API
    # ------------------------------------------------------------------
    def get_extraction_stats(self, operation_id: str | None = None) -> list[dict]:
        """Get aggregate extraction statistics for reporting."""

        base_query = """
            SELECT
                outcome,
                COUNT(*) as count,
                AVG(extraction_time_ms) as avg_time_ms,
                AVG(content_quality_score) as avg_quality_score,
                SUM(is_success) as success_count,
                SUM(is_content_success) as content_success_count,
                SUM(is_technical_failure) as technical_failure_count,
                SUM(is_bot_protection) as bot_protection_count
            FROM extraction_outcomes
        """

        if operation_id:
            query = base_query + " WHERE operation_id = ? GROUP BY outcome"
            params = (operation_id,)
        else:
            query = base_query + " GROUP BY outcome"
            params = ()

        try:
            with self._store.connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            print(f"Failed to get extraction stats: {exc}")
            return []
