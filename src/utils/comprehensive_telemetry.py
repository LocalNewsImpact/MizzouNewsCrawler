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


# Proxy status codes for telemetry database (integer field)
PROXY_STATUS_DISABLED = 0
PROXY_STATUS_SUCCESS = 1
PROXY_STATUS_FAILED = 2
PROXY_STATUS_BYPASSED = 3


def proxy_status_to_int(status: str | None) -> int | None:
    """Convert string proxy status to integer for database storage."""
    if status is None:
        return None
    status_map = {
        "disabled": PROXY_STATUS_DISABLED,
        "success": PROXY_STATUS_SUCCESS,
        "failed": PROXY_STATUS_FAILED,
        "bypassed": PROXY_STATUS_BYPASSED,
    }
    return status_map.get(status.lower())


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
        self.end_time: datetime | None = None
        self.total_duration_ms: float = 0.0

        # HTTP metrics
        self.http_status_code: int | None = None
        self.http_error_type: str | None = None
        self.response_size_bytes = 0
        self.response_time_ms: float = 0.0

        # Method tracking
        self.methods_attempted: list[str] = []
        self.method_timings: dict[str, float] = {}
        self.method_success: dict[str, bool] = {}
        self.method_errors: dict[str, str] = {}
        self.successful_method: str | None = None

        # Field extraction tracking
        self.field_extraction: dict[str, dict[str, Any]] = {}

        # Final field attribution (which method provided each field)
        self.final_field_attribution: dict[str, str] = {}

        # Track alternative extractions (later methods vs. current fields)
        self.alternative_extractions: dict[str, dict[str, Any]] = {}

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
        # 0=disabled, 1=success, 2=failed, 3=bypassed
        self.proxy_status: int | None = None
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
            if "proxy_used" in metadata and not self.proxy_used:
                self.set_proxy_metrics(
                    proxy_used=metadata.get("proxy_used", False),
                    proxy_url=metadata.get("proxy_url"),
                    proxy_authenticated=metadata.get("proxy_authenticated", False),
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
        self.proxy_status = proxy_status_to_int(proxy_status)
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
                # Use DatabaseManager's existing engine
                # This handles Cloud SQL Connector automatically
                from src.models.database import DatabaseManager

                db = DatabaseManager()
                database_url = str(db.engine.url)
                self._database_url = database_url
                # Pass the engine so telemetry uses existing Cloud SQL connection
                self._store = get_store(database_url, engine=db.engine)

        # Track destination schema so telemetry stays compatible across deployments
        self._content_type_strategy: str | None = None
        self._content_type_columns: set[str] | None = None
        self._content_type_warning_logged = False

        # NOTE: Telemetry tables should already exist via Alembic migrations
        # Do NOT create tables at runtime from application code

    # REMOVED: _ensure_telemetry_tables() method
    # Schema changes should be handled via Alembic migrations, NOT at runtime
    # If telemetry tables don't exist, they should be created via:
    # 1. alembic upgrade head (for new deployments)
    # 2. Manual SQL scripts (for existing databases)
    # 3. NOT from application code during normal operation

    def record_extraction(self, metrics: ExtractionMetrics):
        """Record detailed extraction metrics."""

        from sqlalchemy.exc import IntegrityError

        def _do_insert(conn) -> None:
            """Perform the core INSERT for extraction telemetry."""
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
                content_length, is_success, error_message, error_type,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                     ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    is_success,  # Keep as boolean for PostgreSQL compatibility
                    metrics.error_message,
                    metrics.error_type,
                    datetime.utcnow(),  # created_at timestamp
                ),
            )

        def writer(conn):
            # Try insert, on duplicate-key (IntegrityError) attempt a sequence
            # resync for Postgres then retry once. This guards against
            # out-of-sync SERIAL sequences causing 23505 failures.
            try:
                _do_insert(conn)
            except IntegrityError as ie:
                logger.warning("Telemetry insert IntegrityError: %s", ie)
                try:
                    # Only attempt resync if backing store is Postgres
                    if (
                        hasattr(self._store, "_is_postgres")
                        and self._store._is_postgres
                    ):
                        # Try to set sequence to max(id) so nextval yields new id
                        conn.execute(
                            """
                            DO $$
                            DECLARE
                                seq_name text;
                                max_id bigint;
                            BEGIN
                                SELECT pg_get_serial_sequence(
                                    'extraction_telemetry_v2', 'id'
                                ) INTO seq_name;
                                IF seq_name IS NULL THEN
                                    RAISE NOTICE 'No serial sequence found for extraction_telemetry_v2.id';
                                    RETURN;
                                END IF;
                                EXECUTE format(
                                    'SELECT COALESCE(MAX(id), 0) FROM extraction_telemetry_v2'
                                ) INTO max_id;
                                IF max_id IS NULL THEN
                                    max_id := 0;
                                END IF;
                                EXECUTE format('SELECT setval(%L, %s)', seq_name, max_id);
                                RAISE NOTICE 'Resynced sequence % to %', seq_name, max_id;
                            END
                            $$;
                            """,
                        )

                        # Retry insert once
                        try:
                            _do_insert(conn)
                        except IntegrityError as ie2:
                            logger.warning(
                                "Telemetry insert failed again after sequence resync: %s",
                                ie2,
                            )
                            return
                    else:
                        # Non-Postgres stores can't resync sequence; ignore
                        logger.warning(
                            "Telemetry insert IntegrityError on non-Postgres store, ignoring: %s",
                            ie,
                        )
                        return
                except Exception:
                    logger.exception("Exception during telemetry resync attempt")
                    return

            if metrics.http_status_code and metrics.http_error_type:
                now = datetime.utcnow()
                conn.execute(
                    """
                    INSERT INTO http_error_summary
                    (host, status_code, error_type, count, first_seen, last_seen)
                    VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(host, status_code) DO UPDATE SET
                        count = http_error_summary.count + 1,
                        last_seen = ?
                    """,
                    (
                        metrics.host,
                        metrics.http_status_code,
                        metrics.http_error_type,
                        now,
                        now,
                        now,
                    ),
                )

            detection = metrics.content_type_detection
            if detection:
                self._insert_content_type_detection(conn, metrics, detection)

            # Explicit commit to ensure transaction completes
            conn.commit()

        try:
            self._store.submit(writer)
        except (RuntimeError, RecursionError):
            # Telemetry disabled or Cloud SQL incompatibility
            pass
        except Exception as exc:
            # Log but don't fail extraction
            exc_msg = str(exc).split("\n")[0][:80]
            print(f"Warning: Telemetry failed: {type(exc).__name__}: {exc_msg}")

    def _fetch_table_columns(self, conn, table_name: str) -> set[str]:
        """Return lower-case column names for a table."""
        columns: set[str] = set()
        try:
            # Detect database type from connection dialect
            dialect_name = None
            if hasattr(conn, "dialect"):
                dialect_name = conn.dialect.name
            elif hasattr(conn, "engine") and hasattr(conn.engine, "dialect"):
                dialect_name = conn.engine.dialect.name
            elif hasattr(conn, "connection") and hasattr(conn.connection, "engine"):
                dialect_name = conn.connection.engine.dialect.name

            # Fallback: check URL if available
            if not dialect_name:
                try:
                    url_str = str(conn.engine.url) if hasattr(conn, "engine") else None
                    if url_str:
                        dialect_name = "sqlite" if "sqlite" in url_str else "postgresql"
                except Exception:
                    pass

            is_sqlite = dialect_name == "sqlite"

            if is_sqlite:
                # SQLite: Use PRAGMA (cannot use parameterized queries with PRAGMA)
                # Note: table_name is validated to be a string, f-string is safe here
                # TelemetryStore.execute() expects plain SQL string, not TextClause
                cursor = conn.execute(f"PRAGMA table_info({table_name})")
                rows = cursor.fetchall()
                for row in rows:
                    # SQLite pragma returns tuples like (cid, name, type, ...)
                    # Row can be tuple, list, or _RowProxy - all support indexing
                    try:
                        col_name = row[1] if len(row) > 1 else None
                    except (TypeError, KeyError):
                        col_name = getattr(row, "name", None)
                    if col_name:
                        columns.add(str(col_name).lower())
            else:
                # PostgreSQL: Use information_schema with named parameters
                # TelemetryStore.execute() will convert to text() internally
                cursor = conn.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = :table_name
                    """,
                    {"table_name": table_name},
                )
                rows = cursor.fetchall()
                for row in rows:
                    col_name = row[0] if row else None
                    if col_name:
                        columns.add(str(col_name).lower())
        except Exception as e:
            # Introspection failures should not break extraction telemetry
            logger.warning(f"Failed to fetch table columns for {table_name}: {e!r}")
            columns = set()

        return columns

    def _get_column_type(self, conn, table_name: str, column_name: str) -> str | None:
        """Get the data type of a specific column.
        
        Returns the column type in lowercase (e.g., 'character varying', 'double precision', 'text', 'real', 'float').
        Returns None if the column doesn't exist or type cannot be determined.
        
        Note: table_name is validated to prevent SQL injection.
        """
        # Validate table_name to prevent SQL injection
        # Only allow alphanumeric characters, underscores, and hyphens
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', table_name):
            logger.warning(f"Invalid table name: {table_name}")
            return None
        
        try:
            # Detect database type from connection dialect
            dialect_name = None
            if hasattr(conn, "dialect"):
                dialect_name = conn.dialect.name
            elif hasattr(conn, "engine") and hasattr(conn.engine, "dialect"):
                dialect_name = conn.engine.dialect.name
            elif hasattr(conn, "connection") and hasattr(conn.connection, "engine"):
                dialect_name = conn.connection.engine.dialect.name

            # Fallback: check URL if available
            if not dialect_name:
                try:
                    url_str = str(conn.engine.url) if hasattr(conn, "engine") else None
                    if url_str:
                        dialect_name = "sqlite" if "sqlite" in url_str else "postgresql"
                except Exception:
                    pass

            is_sqlite = dialect_name == "sqlite"

            if is_sqlite:
                # Safe to use f-string here since table_name is validated above
                cursor = conn.execute(f"PRAGMA table_info({table_name})")
                rows = cursor.fetchall()
                for row in rows:
                    try:
                        col_name = row[1] if len(row) > 1 else None
                        col_type = row[2] if len(row) > 2 else None
                        if col_name and str(col_name).lower() == column_name.lower():
                            return str(col_type).lower() if col_type else None
                    except (TypeError, KeyError, IndexError):
                        continue
            else:
                # PostgreSQL: Use information_schema
                cursor = conn.execute(
                    """
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = :table_name
                      AND column_name = :column_name
                    """,
                    {"table_name": table_name, "column_name": column_name},
                )
                row = cursor.fetchone()
                if row:
                    return str(row[0]).lower() if row[0] else None
        except Exception as e:
            logger.debug(
                f"Failed to get column type for {table_name}.{column_name}: {e!r}"
            )

        return None

    def _ensure_content_type_strategy(self, conn) -> str | None:
        """Detect which schema version the content type telemetry table uses."""
        if self._content_type_strategy:
            return self._content_type_strategy

        columns = self._fetch_table_columns(conn, "content_type_detection_telemetry")
        self._content_type_columns = columns

        modern_cols = {"status", "confidence", "confidence_score"}
        legacy_cols = {"detected_type", "detection_method"}

        if not columns:
            self._content_type_strategy = "missing"
        elif modern_cols.issubset(columns):
            self._content_type_strategy = "modern"
        elif legacy_cols.issubset(columns):
            self._content_type_strategy = "legacy"
        else:
            self._content_type_strategy = "unsupported"

        if self._content_type_strategy in {"missing", "unsupported"}:
            if not self._content_type_warning_logged:
                logger.warning(
                    "Content type telemetry table unavailable or has unsupported schema; "
                    "telemetry rows will be skipped (strategy=%s)",
                    self._content_type_strategy,
                )
                self._content_type_warning_logged = True
            return None

        return self._content_type_strategy

    def _insert_content_type_detection(
        self, conn, metrics: ExtractionMetrics, detection: dict[str, Any]
    ) -> None:
        """Insert content type telemetry, adapting to legacy schemas when needed."""
        strategy = self._ensure_content_type_strategy(conn)
        if not strategy:
            return

        try:
            if strategy == "modern":
                # Defensive check: If confidence column is numeric type (legacy schema),
                # convert string confidence to numeric value
                confidence_value = detection.get("confidence")
                confidence_col_type = self._get_column_type(
                    conn, "content_type_detection_telemetry", "confidence"
                )
                
                # If confidence column is numeric (float/double/real), use numeric value
                if confidence_col_type and any(
                    numeric_type in confidence_col_type
                    for numeric_type in ["double", "float", "real", "numeric"]
                ):
                    # Schema mismatch: confidence column is numeric but we have string value
                    # Use the numeric confidence_score or convert label to numeric
                    confidence_value = self._resolve_numeric_confidence(detection)
                    logger.debug(
                        "Schema mismatch detected: confidence column is numeric type (%s), "
                        "using numeric value %s instead of string label",
                        confidence_col_type,
                        confidence_value,
                    )
                
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
                        confidence_value,
                        detection.get("confidence_score"),
                        detection.get("reason"),
                        (
                            json.dumps(evidence_payload)
                            if evidence_payload is not None
                            else None
                        ),
                        detection.get("version"),
                        self._coerce_detected_at(detection.get("detected_at")),
                    ),
                )
            elif strategy == "legacy":
                evidence_json = (
                    json.dumps(detection.get("evidence"))
                    if detection.get("evidence") is not None
                    else None
                )

                conn.execute(
                    """
                    INSERT INTO content_type_detection_telemetry (
                        operation_id, article_id, url, host,
                        http_content_type, detected_type, detection_method,
                        confidence, file_extension, mime_type, byte_signature,
                        content_sample, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metrics.operation_id,
                        metrics.article_id,
                        metrics.url,
                        metrics.host,
                        None,
                        detection.get("status"),
                        detection.get("reason") or detection.get("version"),
                        self._resolve_numeric_confidence(detection),
                        None,
                        None,
                        None,
                        evidence_json,
                        None,
                    ),
                )
        except Exception:  # pragma: no cover - defensive telemetry handling
            if not self._content_type_warning_logged:
                logger.exception(
                    "Failed to insert content type telemetry (strategy=%s)", strategy
                )
                self._content_type_warning_logged = True

    @staticmethod
    def _resolve_numeric_confidence(detection: dict[str, Any]) -> float | None:
        score = detection.get("confidence_score")
        if isinstance(score, (int, float)):
            try:
                return float(score)
            except (TypeError, ValueError):
                return None

        label = detection.get("confidence")
        if isinstance(label, str):
            mapping = {
                "very_high": 0.95,
                "high": 0.85,
                "medium": 0.5,
                "low": 0.25,
            }
            return mapping.get(label.lower())
        return None

    @staticmethod
    def _coerce_detected_at(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            candidate = value.strip()
            if candidate.endswith("Z"):
                candidate = candidate[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                return None
        return None

    def get_error_summary(self, days: int = 7) -> list:
        """Get HTTP error summary for the last N days."""
        # Use Python datetime to avoid SQL dialect issues
        from datetime import timedelta

        cutoff_time = datetime.utcnow() - timedelta(days=days)

        with self._store.connection() as conn:
            cursor = conn.execute(
                """
                SELECT host, status_code, error_type, count, last_seen
                FROM http_error_summary
                WHERE last_seen >= ?
                ORDER BY count DESC, last_seen DESC
                """,
                (cutoff_time,),
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
            # Use Python datetime to avoid SQL dialect issues
            from datetime import timedelta

            cutoff_time = datetime.utcnow() - timedelta(days=days)
            where_clauses.append("created_at >= ?")
            params.append(cutoff_time)

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        query = (
            "SELECT article_id, operation_id, url, publisher, host, status, "
            "confidence, confidence_score, reason, evidence, version, "
            "detected_at, created_at "
            "FROM content_type_detection_telemetry"
            f"{where_sql} "
            f"ORDER BY COALESCE(detected_at, created_at) DESC LIMIT {limit}"
        )

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
