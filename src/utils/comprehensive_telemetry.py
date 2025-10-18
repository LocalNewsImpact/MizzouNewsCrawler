"""
Enhanced extraction telemetry system for comprehensive performance tracking.

This module provides detailed tracking of extraction performance across
methods, publishers, and error conditions to optimize extraction strategies.
"""

import json
import logging
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.telemetry.store import TelemetryStore, get_store

logger = logging.getLogger(__name__)


class ExtractionMetrics:
    """Tracks detailed metrics for a single extraction operation."""

    def __init__(self, operation_id: str, article_id: str, url: str, publisher: str):
        self.operation_id = operation_id
        self.article_id = article_id
        self.url = url
        self.publisher = publisher
        self.host = urlparse(url).netloc

        # Overall timing
        self.start_time = datetime.utcnow()
        self.end_time = None
        self.total_duration_ms = 0

        # HTTP metrics
        self.http_status_code = None
        self.http_error_type = None
        self.response_size_bytes = 0
        self.response_time_ms = 0

        # Method tracking
        self.methods_attempted = []
        self.method_timings = {}
        self.method_success = {}
        self.method_errors = {}
        self.successful_method = None

        # Field extraction tracking
        self.field_extraction = {}

        # Final field attribution (which method provided each field)
        self.final_field_attribution = {}

        # Track alternative extractions (later methods vs. current fields)
        self.alternative_extractions = {}

        # Final results
        self.extracted_fields = {
            "title": False,
            "author": False,
            "content": False,
            "publish_date": False,
        }
        self.content_length = 0
        self.is_success = False

        # Error tracking
        self.error_message: str | None = None
        self.error_type: str | None = None

        # Content type detection
        self.content_type_detection: dict[str, Any] | None = None

        # Proxy metrics
        self.proxy_used: bool = False
        self.proxy_url: str | None = None
        self.proxy_authenticated: bool = False
        self.proxy_status: str | None = None  # success, failed, bypassed, disabled
        self.proxy_error: str | None = None

    def start_method(self, method_name: str):
        """Start timing a specific extraction method."""
        self.methods_attempted.append(method_name)
        self.method_timings[method_name] = time.time()

    def end_method(
        self,
        method_name: str,
        success: bool,
        error: str | None = None,
        extracted_fields: dict[str, Any] | None = None,
    ):
        """End timing and record results for a method."""
        if method_name in self.method_timings:
            duration = (time.time() - self.method_timings[method_name]) * 1000
            self.method_timings[method_name] = duration

        self.method_success[method_name] = success
        if error:
            self.method_errors[method_name] = error

        if success and not self.successful_method:
            self.successful_method = method_name

        # Track field-level success (always track, even for failed methods)
        if extracted_fields is not None:
            self.field_extraction[method_name] = {
                "title": bool(extracted_fields.get("title")),
                "author": bool(extracted_fields.get("author")),
                "content": bool(extracted_fields.get("content")),
                "publish_date": bool(extracted_fields.get("publish_date")),
            }

            # Extract HTTP status from metadata if available
            metadata = extracted_fields.get("metadata", {})
            http_status = metadata.get("http_status")
            if http_status and self.http_status_code is None:
                # Use first HTTP status we encounter
                self.set_http_metrics(http_status, 0, 0)

            # Extract proxy info from metadata if available
            if (
                "proxy_used" in metadata
                and not self.proxy_used
            ):
                self.set_proxy_metrics(
                    proxy_used=metadata.get("proxy_used", False),
                    proxy_url=metadata.get("proxy_url"),
                    proxy_authenticated=metadata.get(
                        "proxy_authenticated", False
                    ),
                    proxy_status=metadata.get("proxy_status"),
                    proxy_error=metadata.get("proxy_error"),
                )

    def record_alternative_extraction(
        self,
        method_name: str,
        field_name: str,
        alternative_value: str,
        current_value: str,
    ):
        """Record when a later method extracts an alternative for filled field.

        Args:
            method_name: The method that found the alternative
            field_name: The field that was extracted alternatively
            alternative_value: The value the later method found
            current_value: The current value already in the result
        """
        if method_name not in self.alternative_extractions:
            self.alternative_extractions[method_name] = {}

        self.alternative_extractions[method_name][field_name] = {
            "alternative_value": alternative_value[:200],  # Truncate
            "current_value": current_value[:200],  # Truncate
            "values_differ": alternative_value != current_value,
        }

    def set_content_type_detection(self, detection: dict[str, Any] | None):
        """Attach content type detection payload for telemetry."""
        self.content_type_detection = detection

    def set_http_metrics(
        self, status_code: int, response_size: int, response_time_ms: float
    ):
        """Record HTTP-level metrics."""
        self.http_status_code = status_code
        self.response_size_bytes = response_size
        self.response_time_ms = response_time_ms

        # Categorize HTTP errors
        if 300 <= status_code < 400:
            self.http_error_type = "3xx_redirect"
        elif 400 <= status_code < 500:
            self.http_error_type = "4xx_client_error"
        elif status_code >= 500:
            self.http_error_type = "5xx_server_error"

    def set_proxy_metrics(
        self,
        proxy_used: bool,
        proxy_url: str | None = None,
        proxy_authenticated: bool = False,
        proxy_status: str | None = None,
        proxy_error: str | None = None,
    ):
        """Record proxy-level metrics.
        
        Args:
            proxy_used: Whether proxy was used for this request
            proxy_url: The proxy URL if used
            proxy_authenticated: Whether proxy credentials were present
            proxy_status: Status of proxy usage: success, failed, bypassed, disabled
            proxy_error: Error message if proxy failed
        """
        self.proxy_used = proxy_used
        self.proxy_url = proxy_url
        self.proxy_authenticated = proxy_authenticated
        self.proxy_status = proxy_status
        if proxy_error:
            # Truncate long error messages
            self.proxy_error = proxy_error[:500]

    def finalize(self, final_result: dict[str, Any]):
        """Finalize metrics with the overall extraction result."""
        self.end_time = datetime.utcnow()
        duration_sec = (self.end_time - self.start_time).total_seconds()
        self.total_duration_ms = duration_sec * 1000

        # Update final field extraction success
        if final_result:
            self.extracted_fields = {
                "title": bool(final_result.get("title")),
                "author": bool(final_result.get("author")),
                "content": bool(final_result.get("content")),
                "publish_date": bool(final_result.get("publish_date")),
            }

            # Capture final field attribution from metadata
            metadata = final_result.get("metadata", {})
            extraction_methods = metadata.get("extraction_methods", {})
            if extraction_methods:
                self.final_field_attribution = extraction_methods

            self.content_length = len(final_result.get("content") or "")
            has_title = bool(final_result.get("title"))
            has_content = bool(final_result.get("content"))
            self.is_success = has_title and has_content


class ComprehensiveExtractionTelemetry:
    """Enhanced telemetry system for extraction performance analysis."""

    def __init__(
        self,
        db_path: str | None = None,
        store: TelemetryStore | None = None,
    ) -> None:
        """Initialize telemetry system."""
        if store is not None:
            self._store = store
            self._database_url = None  # Unknown when store provided directly
        else:
            if db_path is not None:
                resolved = Path(db_path)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                database_url = f"sqlite:///{resolved}"
                self._database_url = database_url
                self._store = TelemetryStore(
                    database=database_url,
                    async_writes=False,
                )
            else:
                # Use DatabaseManager to get the correct database URL
                # This handles Cloud SQL Connector automatically
                from src.models.database import DatabaseManager
                db = DatabaseManager()
                database_url = str(db.engine.url)
                self._database_url = database_url
                self._store = get_store(database_url)

        try:
            self._ensure_telemetry_tables()
        except Exception as e:
            logger.warning(f"Failed to initialize telemetry tables: {e}")
            logger.warning("Continuing without telemetry...")

    def _ensure_telemetry_tables(self):
        """Create telemetry tables if they don't exist."""
        # Detect if we're using PostgreSQL or SQLite
        is_postgres = (
            self._database_url and
            self._database_url.startswith("postgresql")
        )
        
        # Use appropriate auto-increment syntax
        if is_postgres:
            auto_id = "SERIAL PRIMARY KEY"
        else:
            auto_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
        
        with self._store.connection() as conn:
            # Enhanced extraction telemetry table
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS extraction_telemetry_v2 (
                    id {auto_id},
                    operation_id TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    publisher TEXT,
                    host TEXT,

                    -- Timing metrics
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    total_duration_ms REAL,

                    -- HTTP metrics
                    http_status_code INTEGER,
                    http_error_type TEXT,
                    response_size_bytes INTEGER,
                    response_time_ms REAL,

                    -- Proxy metrics
                    proxy_used BOOLEAN,
                    proxy_url TEXT,
                    proxy_authenticated BOOLEAN,
                    proxy_status TEXT,
                    proxy_error TEXT,

                    -- Method tracking
                    methods_attempted TEXT,
                    successful_method TEXT,
                    method_timings TEXT,
                    method_success TEXT,
                    method_errors TEXT,

                    -- Field extraction tracking
                    field_extraction TEXT,
                    extracted_fields TEXT,
                    final_field_attribution TEXT,
                    alternative_extractions TEXT,

                    -- Results
                    content_length INTEGER,
                    is_success BOOLEAN,
                    error_message TEXT,
                    error_type TEXT,

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Add alternative_extractions column if it doesn't exist
            try:
                conn.execute(
                    """
                    ALTER TABLE extraction_telemetry_v2
                    ADD COLUMN alternative_extractions TEXT
                """
                )
                print("Added alternative_extractions column")
            except Exception:
                # Column already exists
                pass

            # Add proxy metrics columns if they don't exist
            proxy_columns = [
                ("proxy_used", "BOOLEAN"),
                ("proxy_url", "TEXT"),
                ("proxy_authenticated", "BOOLEAN"),
                ("proxy_status", "TEXT"),
                ("proxy_error", "TEXT"),
            ]
            for column_name, column_type in proxy_columns:
                try:
                    conn.execute(
                        f"""
                        ALTER TABLE extraction_telemetry_v2
                        ADD COLUMN {column_name} {column_type}
                        """
                    )
                    print(f"Added {column_name} column")
                except Exception:
                    # Column already exists
                    pass

            # HTTP error tracking
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS http_error_summary (
                    id {auto_id},
                    host TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    error_type TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    UNIQUE(host, status_code)
                )
            """
            )

            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS content_type_detection_telemetry (
                    id {auto_id},
                    article_id TEXT NOT NULL,
                    operation_id TEXT,
                    url TEXT NOT NULL,
                    publisher TEXT,
                    host TEXT,
                    status TEXT NOT NULL,
                    confidence TEXT,
                    confidence_score REAL,
                    reason TEXT,
                    evidence TEXT,
                    version TEXT,
                    detected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            try:
                conn.execute(
                    """
                    ALTER TABLE content_type_detection_telemetry
                    ADD COLUMN confidence_score REAL
                    """
                )
            except Exception:
                pass

            conn.commit()

    def record_extraction(self, metrics: ExtractionMetrics):
        """Record detailed extraction metrics."""

        def writer(conn):
            is_success = bool(metrics.is_success)
            if not is_success:
                if metrics.successful_method:
                    is_success = True
                else:
                    is_success = any(metrics.method_success.values())
            conn.execute(
                """
                INSERT INTO extraction_telemetry_v2 (
                    operation_id, article_id, url, publisher, host,
                    start_time, end_time, total_duration_ms,
                    http_status_code, http_error_type,
                    response_size_bytes, response_time_ms,
                    proxy_used, proxy_url, proxy_authenticated,
                    proxy_status, proxy_error,
                    methods_attempted, successful_method,
                    method_timings, method_success, method_errors,
                    field_extraction, extracted_fields,
                    final_field_attribution, alternative_extractions,
                    content_length, is_success, error_message, error_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metrics.operation_id,
                    metrics.article_id,
                    metrics.url,
                    metrics.publisher,
                    metrics.host,
                    metrics.start_time,
                    metrics.end_time,
                    metrics.total_duration_ms,
                    metrics.http_status_code,
                    metrics.http_error_type,
                    metrics.response_size_bytes,
                    metrics.response_time_ms,
                    (
                        int(metrics.proxy_used)
                        if metrics.proxy_used is not None
                        else None
                    ),
                    metrics.proxy_url,
                    (
                        int(metrics.proxy_authenticated)
                        if metrics.proxy_authenticated is not None
                        else None
                    ),
                    metrics.proxy_status,
                    metrics.proxy_error,
                    json.dumps(metrics.methods_attempted),
                    metrics.successful_method,
                    json.dumps(metrics.method_timings),
                    json.dumps(metrics.method_success),
                    json.dumps(metrics.method_errors),
                    json.dumps(metrics.field_extraction),
                    json.dumps(metrics.extracted_fields),
                    json.dumps(metrics.final_field_attribution),
                    json.dumps(metrics.alternative_extractions),
                    metrics.content_length,
                    int(is_success),
                    metrics.error_message,
                    metrics.error_type,
                ),
            )

            if metrics.http_status_code and metrics.http_error_type:
                now = datetime.utcnow()
                conn.execute(
                    """
                    INSERT INTO http_error_summary
                    (host, status_code, error_type, count, last_seen)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(host, status_code) DO UPDATE SET
                        count = count + 1,
                        last_seen = ?
                    """,
                    (
                        metrics.host,
                        metrics.http_status_code,
                        metrics.http_error_type,
                        now,
                        now,
                    ),
                )

            detection = metrics.content_type_detection
            if detection:
                evidence_payload = detection.get("evidence")
                conn.execute(
                    """
                    INSERT INTO content_type_detection_telemetry (
                        article_id, operation_id, url, publisher, host,
                        status, confidence, confidence_score, reason,
                        evidence, version, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metrics.article_id,
                        metrics.operation_id,
                        metrics.url,
                        metrics.publisher,
                        metrics.host,
                        detection.get("status"),
                        detection.get("confidence"),
                        detection.get("confidence_score"),
                        detection.get("reason"),
                        (
                            json.dumps(evidence_payload)
                            if evidence_payload is not None
                            else None
                        ),
                        detection.get("version"),
                        detection.get("detected_at"),
                    ),
                )

        self._store.submit(writer)

    def get_error_summary(self, days: int = 7) -> list:
        """Get HTTP error summary for the last N days."""
        with self._store.connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT host, status_code, error_type, count, last_seen
                FROM http_error_summary
                WHERE last_seen >= datetime('now', '-{days} days')
                ORDER BY count DESC, last_seen DESC
                """
            )
            try:
                columns = [col[0] for col in cursor.description]
                return [
                    dict(zip(columns, row, strict=False)) for row in cursor.fetchall()
                ]
            finally:
                cursor.close()

    def get_content_type_detections(
        self,
        *,
        limit: int = 200,
        statuses: Sequence[str] | None = None,
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent content-type detections for review."""

        where_clauses: list[str] = []
        params: list[Any] = []

        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where_clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)

        if days is not None:
            where_clauses.append("created_at >= datetime('now', ?)")
            params.append(f"-{days} days")

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        query = (
            "SELECT article_id, operation_id, url, publisher, host, status, "
            "confidence, confidence_score, reason, evidence, version, "
            "detected_at, created_at "
            "FROM content_type_detection_telemetry"
            f"{where_sql} "
            "ORDER BY COALESCE(detected_at, created_at) DESC LIMIT ?"
        )
        params.append(limit)

        with self._store.connection() as conn:
            cursor = conn.execute(query, params)
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()

        results: list[dict[str, Any]] = []
        for row in rows:
            (
                article_id,
                operation_id,
                url,
                publisher,
                host,
                status,
                confidence,
                confidence_score,
                reason,
                evidence_json,
                version,
                detected_at,
                created_at,
            ) = row
            try:
                evidence = json.loads(evidence_json) if evidence_json else None
            except (json.JSONDecodeError, TypeError):
                evidence = evidence_json

            results.append(
                {
                    "article_id": article_id,
                    "operation_id": operation_id,
                    "url": url,
                    "publisher": publisher,
                    "host": host,
                    "status": status,
                    "confidence": confidence,
                    "confidence_score": confidence_score,
                    "reason": reason,
                    "evidence": evidence,
                    "version": version,
                    "detected_at": detected_at,
                    "created_at": created_at,
                }
            )

        return results

    def get_method_effectiveness(
        self, publisher: str | None = None
    ) -> list[dict[str, Any]]:
        """Get method effectiveness stats."""
        with self._store.connection() as conn:
            where_clause = ""
            params: list[Any] = []

            if publisher:
                where_clause = "WHERE publisher = ?"
                params.append(publisher)

            query = (
                "SELECT method_timings, method_success, is_success "
                "FROM extraction_telemetry_v2 "
            )
            if where_clause:
                query += where_clause

            cursor = conn.execute(query, params)
            try:
                method_stats: dict[str, dict[str, float]] = {}
                for row in cursor.fetchall():
                    timings_json, success_json, _overall_success = row
                    if not timings_json:
                        continue

                    try:
                        timings = json.loads(timings_json)
                        successes = json.loads(success_json) if success_json else {}
                    except (json.JSONDecodeError, TypeError):
                        continue

                    for method, timing in timings.items():
                        if method not in method_stats:
                            method_stats[method] = {
                                "count": 0,
                                "total_duration": 0.0,
                                "success_count": 0,
                            }

                        stats = method_stats[method]
                        stats["count"] += 1
                        stats["total_duration"] += timing
                        if successes.get(method, False):
                            stats["success_count"] += 1
            finally:
                cursor.close()

        method_results: list[dict[str, Any]] = []
        for method, stats in method_stats.items():
            count = stats["count"]
            avg_duration = stats["total_duration"] / count if count else 0.0
            success_rate = stats["success_count"] / count if count else 0.0
            method_results.append(
                {
                    "method_type": method,
                    "successful_method": method,
                    "count": count,
                    "avg_duration": avg_duration,
                    "success_rate": success_rate,
                }
            )

        method_results.sort(key=lambda item: item["count"], reverse=True)
        return method_results

    def get_publisher_stats(self) -> list[dict[str, Any]]:
        """Get per-publisher performance statistics."""
        with self._store.connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    publisher,
                    host,
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successful,
                    AVG(total_duration_ms) as avg_duration_ms,
                    successful_method as most_common_method
                FROM extraction_telemetry_v2
                GROUP BY publisher, host, successful_method
                ORDER BY total_attempts DESC
                """
            )
            try:
                columns = [col[0] for col in cursor.description]
                return [
                    dict(zip(columns, row, strict=False)) for row in cursor.fetchall()
                ]
            finally:
                cursor.close()

    def get_field_extraction_stats(
        self,
        publisher: str | None = None,
        method: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get field-level extraction success statistics by method."""
        with self._store.connection() as conn:
            where_parts: list[str] = []
            params: list[Any] = []

            if publisher:
                where_parts.append("publisher = ?")
                params.append(publisher)

            where_clause = ""
            if where_parts:
                where_clause = "WHERE " + " AND ".join(where_parts)

            query = (
                "SELECT field_extraction, methods_attempted, "
                "successful_method FROM extraction_telemetry_v2 "
            )
            if where_clause:
                query += where_clause

            cursor = conn.execute(query, params)
            method_field_stats: dict[str, dict[str, int]] = {}
            try:
                for row in cursor.fetchall():
                    field_extraction_json, methods_json, _successful = row

                    try:
                        methods = json.loads(methods_json) if methods_json else []
                        field_data = (
                            json.loads(field_extraction_json)
                            if field_extraction_json
                            else {}
                        )
                    except (json.JSONDecodeError, TypeError):
                        continue

                    for method_name in methods:
                        if method and method_name != method:
                            continue

                        stats = method_field_stats.setdefault(
                            method_name,
                            {
                                "count": 0,
                                "title_success": 0,
                                "author_success": 0,
                                "content_success": 0,
                                "date_success": 0,
                            },
                        )

                        stats["count"] += 1
                        method_fields = field_data.get(method_name, {})
                        if method_fields.get("title"):
                            stats["title_success"] += 1
                        if method_fields.get("author"):
                            stats["author_success"] += 1
                        if method_fields.get("content"):
                            stats["content_success"] += 1
                        if method_fields.get("publish_date"):
                            stats["date_success"] += 1
            finally:
                cursor.close()

        results: list[dict[str, Any]] = []
        for method_name, stats in method_field_stats.items():
            count = stats["count"]
            denominator = count if count else 1
            results.append(
                {
                    "method": method_name,
                    "count": count,
                    "title_success_rate": stats["title_success"] / denominator,
                    "author_success_rate": stats["author_success"] / denominator,
                    "content_success_rate": stats["content_success"] / denominator,
                    "date_success_rate": stats["date_success"] / denominator,
                }
            )

        results.sort(key=lambda item: item["count"], reverse=True)
        return results
