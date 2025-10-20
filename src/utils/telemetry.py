"""
Telemetry and tracking system for MizzouNewsCrawler operations.

This module provides comprehensive tracking and telemetry for all crawler
operations, designed to integrate with the existing React frontend and backend
API.

Features:
- Real-time operation tracking
- Progress reporting with metrics
- Error tracking and alerting
- API endpoint integration
- WebSocket support for live updates
- Structured logging with correlation IDs
"""

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import requests
from sqlalchemy.exc import SQLAlchemyError

from src.telemetry.store import TelemetryStore, get_store

DB_ERRORS = (sqlite3.OperationalError, SQLAlchemyError)


def _is_missing_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "no such table" in message or "does not exist" in message


class OperationType(str, Enum):
    """Types of crawler operations."""

    LOAD_SOURCES = "load_sources"
    CRAWL_DISCOVERY = "crawl_discovery"
    CONTENT_EXTRACTION = "content_extraction"
    ML_ANALYSIS = "ml_analysis"
    DATA_EXPORT = "data_export"


class OperationStatus(str, Enum):
    """Status of operations."""

    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DiscoveryMethod(str, Enum):
    """Discovery methods for URL finding."""

    RSS_FEED = "rss_feed"
    NEWSPAPER4K = "newspaper4k"
    STORYSNIFFER = "storysniffer"


class HTTPStatusCategory(str, Enum):
    """HTTP status code categories for tracking."""

    SUCCESS = "2xx"
    REDIRECT = "3xx"
    CLIENT_ERROR = "4xx"
    SERVER_ERROR = "5xx"


class DiscoveryMethodStatus(str, Enum):
    """Status of discovery methods for sources."""

    SUCCESS = "success"
    NO_FEED = "no_feed"  # 404 on RSS feeds
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    PARSE_ERROR = "parse_error"
    BLOCKED = "blocked"  # 403, 429, etc.
    SERVER_ERROR = "server_error"  # 5xx errors
    SKIPPED = "skipped"


class FailureType(str, Enum):
    """Types of site/operation failures."""

    NETWORK_ERROR = "network_error"
    CLOUDFLARE_PROTECTION = "cloudflare_protection"
    PARSING_ERROR = "parsing_error"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    SSL_ERROR = "ssl_error"
    CONTENT_ERROR = "content_error"
    RSS_ERROR = "rss_error"
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


_NETWORK_ERROR_KEYWORDS: tuple[str, ...] = (
    "connection",
    "network",
    "dns",
    "hostname",
    "resolve",
)

_SSL_ERROR_KEYWORDS: tuple[str, ...] = (
    "ssl",
    "tls",
    "certificate",
    "handshake",
)

_TIMEOUT_KEYWORDS: tuple[str, ...] = (
    "timeout",
    "timed out",
    "read timeout",
)

_RATE_LIMIT_KEYWORDS: tuple[str, ...] = (
    "rate limit",
    "too many requests",
    "429",
)

_AUTH_ERROR_KEYWORDS: tuple[str, ...] = (
    "unauthorized",
    "forbidden",
    "authentication",
    "401",
    "403",
)

_CONTENT_ERROR_KEYWORDS: tuple[str, ...] = (
    "content",
    "empty",
    "no articles",
    "no data",
)


@dataclass
class OperationMetrics:
    """Metrics for tracking operation progress."""

    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    success_rate: float = 0.0
    items_per_second: float = 0.0
    estimated_completion: datetime | None = None
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    # Site-specific failure tracking
    failed_sites: int = 0
    site_failures: list["SiteFailure"] | None = None

    def __post_init__(self):
        if self.site_failures is None:
            self.site_failures = []


@dataclass
class SiteFailure:
    """Details about a site-specific failure."""

    site_url: str
    site_name: str | None
    failure_type: FailureType
    error_message: str
    failure_time: datetime
    retry_count: int = 0
    http_status: int | None = None
    response_time_ms: float | None = None
    discovery_method: str | None = None  # RSS, newspaper4k, storysniffer
    error_details: dict[str, Any] | None = None

    def __post_init__(self):
        if self.error_details is None:
            self.error_details = {}
        if self.failure_time is None:
            self.failure_time = datetime.now(timezone.utc)


@dataclass
class OperationEvent:
    """Single operation event for tracking."""

    event_id: str
    operation_id: str
    operation_type: OperationType
    status: OperationStatus
    timestamp: datetime
    user_id: str | None = None
    session_id: str | None = None
    message: str = ""
    details: dict[str, Any] | None = None
    metrics: OperationMetrics | None = None
    error_details: dict[str, Any] | None = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class HTTPStatusTracking:
    """Track HTTP status codes for discovery methods."""

    source_id: str
    source_url: str
    discovery_method: DiscoveryMethod
    attempted_url: str
    status_code: int
    status_category: HTTPStatusCategory
    response_time_ms: float
    timestamp: datetime
    operation_id: str
    error_message: str | None = None
    content_length: int | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class DiscoveryMethodEffectiveness:
    """Track effectiveness of discovery methods per source."""

    source_id: str
    source_url: str
    discovery_method: DiscoveryMethod
    status: DiscoveryMethodStatus
    articles_found: int
    success_rate: float
    last_attempt: datetime
    attempt_count: int
    avg_response_time_ms: float
    last_status_codes: list[int]  # Recent status codes
    notes: str | None = None

    def __post_init__(self):
        if self.last_attempt is None:
            self.last_attempt = datetime.now(timezone.utc)
        if not self.last_status_codes:
            self.last_status_codes = []


def _apply_schema(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    """Execute a series of DDL statements on the provided connection."""

    cursor = conn.cursor()
    try:
        for statement in statements:
            cursor.execute(statement)
        conn.commit()
    finally:
        cursor.close()


def _safe_json_dumps(value: Any) -> str | None:
    """Serialize values to JSON, falling back to a string representation."""

    if value is None:
        return None

    try:
        return json.dumps(value)
    except TypeError:
        if isinstance(value, dict):
            coerced = {str(k): str(v) for k, v in value.items()}
            return json.dumps(coerced)
        if isinstance(value, (list, tuple)):
            return json.dumps([str(item) for item in value])

    return json.dumps(str(value))


def _format_timestamp(value: datetime) -> str:
    """Normalize datetimes for SQLite storage."""

    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


_OPERATIONS_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS operations (
        id TEXT PRIMARY KEY,
        operation_type TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP NULL,
        user_id TEXT,
        session_id TEXT,
        parameters TEXT,
        metrics TEXT,
        error_details TEXT,
        result_summary TEXT
    )
    """,
)

_HTTP_STATUS_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS http_status_tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        source_url TEXT NOT NULL,
        discovery_method TEXT NOT NULL,
        attempted_url TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        status_category TEXT NOT NULL,
        response_time_ms REAL NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        operation_id TEXT NOT NULL,
        error_message TEXT,
        content_length INTEGER
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_http_source_method
    ON http_status_tracking (source_id, discovery_method)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_http_status_code
    ON http_status_tracking (status_code)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_http_timestamp
    ON http_status_tracking (timestamp)
    """,
)

_DISCOVERY_METHOD_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS discovery_method_effectiveness (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        source_url TEXT NOT NULL,
        discovery_method TEXT NOT NULL,
        status TEXT NOT NULL,
        articles_found INTEGER NOT NULL DEFAULT 0,
        success_rate REAL NOT NULL DEFAULT 0.0,
        last_attempt TIMESTAMP NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        avg_response_time_ms REAL NOT NULL DEFAULT 0.0,
        last_status_codes TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_effectiveness_source_method
    ON discovery_method_effectiveness (source_id, discovery_method)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_effectiveness_source
    ON discovery_method_effectiveness (source_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_effectiveness_method
    ON discovery_method_effectiveness (discovery_method)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_effectiveness_success_rate
    ON discovery_method_effectiveness (success_rate)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_effectiveness_last_attempt
    ON discovery_method_effectiveness (last_attempt)
    """,
)

_DISCOVERY_OUTCOMES_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS discovery_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        outcome TEXT NOT NULL,
        articles_found INTEGER NOT NULL DEFAULT 0,
        articles_new INTEGER NOT NULL DEFAULT 0,
        articles_duplicate INTEGER NOT NULL DEFAULT 0,
        articles_expired INTEGER NOT NULL DEFAULT 0,
        methods_attempted TEXT NOT NULL,
        method_used TEXT,
        error_details TEXT,
        http_status INTEGER,
        discovery_time_ms REAL NOT NULL DEFAULT 0.0,
        is_success BOOLEAN NOT NULL DEFAULT 0,
        is_content_success BOOLEAN NOT NULL DEFAULT 0,
        is_technical_failure BOOLEAN NOT NULL DEFAULT 0,
        metadata TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discovery_operation
    ON discovery_outcomes (operation_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discovery_source
    ON discovery_outcomes (source_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discovery_outcome
    ON discovery_outcomes (outcome)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discovery_success
    ON discovery_outcomes (is_success)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discovery_content_success
    ON discovery_outcomes (is_content_success)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discovery_timestamp
    ON discovery_outcomes (timestamp)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discovery_source_outcome
    ON discovery_outcomes (source_id, outcome)
    """,
)

_JOBS_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        job_name TEXT,
        started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP,
        exit_status TEXT,
        params TEXT,
        commit_sha TEXT,
        environment TEXT,
        artifact_paths TEXT,
        logs_path TEXT,
        records_processed INTEGER,
        records_created INTEGER,
        records_updated INTEGER,
        errors_count INTEGER
    )
    """,
)

_BASE_SCHEMA = (
    *_JOBS_SCHEMA,
    *_OPERATIONS_SCHEMA,
    *_HTTP_STATUS_SCHEMA,
    *_DISCOVERY_METHOD_SCHEMA,
    *_DISCOVERY_OUTCOMES_SCHEMA,
)


def _parse_timestamp(value: str | None) -> datetime:
    """Parse a SQLite timestamp string into a timezone-aware datetime."""

    if not value:
        return datetime.now(timezone.utc)

    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class TelemetryReporter:
    """Handles sending telemetry data to external APIs."""

    def __init__(self, api_base_url: str | None = None, api_key: str | None = None):
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)

        # Set up headers for API requests
        if api_key:
            self.session.headers.update(
                {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
            )

    def send_operation_event(self, event: OperationEvent) -> bool:
        """Send operation event to external API."""
        if not self.api_base_url:
            return False
        try:
            url = f"{self.api_base_url}/api/v1/telemetry/operations"
            payload = self._serialize_event(event)

            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()

            self.logger.debug(f"Sent telemetry event {event.event_id} to API")
            return True

        except Exception as e:
            self.logger.warning(f"Failed to send telemetry event: {e}")
            return False

    def send_progress_update(
        self, operation_id: str, metrics: OperationMetrics
    ) -> bool:
        """Send progress update to external API."""
        if not self.api_base_url:
            return False

        try:
            url = f"{self.api_base_url}/api/v1/telemetry/progress/{operation_id}"
            payload = asdict(metrics)
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()

            response = self.session.put(url, json=payload, timeout=10)
            response.raise_for_status()

            return True

        except Exception as e:
            self.logger.warning(f"Failed to send progress update: {e}")
            return False

    def _serialize_event(self, event: OperationEvent) -> dict[str, Any]:
        """Serialize event for API transmission."""
        data = asdict(event)
        data["timestamp"] = event.timestamp.isoformat()

        if event.metrics:
            data["metrics"] = asdict(event.metrics)
            if event.metrics.estimated_completion:
                data["metrics"][
                    "estimated_completion"
                ] = event.metrics.estimated_completion.isoformat()

        return data


class OperationTracker:
    """Main tracking system for crawler operations."""

    def __init__(
        self,
        store: Any | None = None,
        *,
        telemetry_reporter: TelemetryReporter | None = None,
        database_url: str | None = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)

        # If no database_url provided, use DatabaseManager to get Cloud SQL connection
        if database_url is None:
            from src.models.database import DatabaseManager

            db = DatabaseManager()
            database_url = str(db.engine.url)

        self.database_url = database_url
        self._store = self._resolve_store(store, database_url)
        if not getattr(self._store, "async_writes", True):
            self.logger.debug(
                "TelemetryTracker running in synchronous mode; job writes immediate"
            )
        self.telemetry_reporter = telemetry_reporter
        self.active_operations: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

        self._ensure_base_schema()

    def _resolve_operation_type(self, operation_id: str) -> OperationType:
        operation = self.active_operations.get(operation_id, {})
        op_type = operation.get("operation_type")
        if isinstance(op_type, OperationType):
            return op_type
        return OperationType.LOAD_SOURCES

    def _resolve_store(
        self,
        candidate: Any | None,
        database_url: str,
    ) -> TelemetryStore:
        if isinstance(candidate, TelemetryStore):
            return candidate

        if candidate is None:
            return TelemetryStore(database=database_url, async_writes=False)

        if hasattr(candidate, "connect") or hasattr(candidate, "execute"):
            engine_url = getattr(candidate, "url", None)
            if engine_url is not None:
                self.logger.debug(
                    "Received engine; initializing dedicated TelemetryStore from %s",
                    engine_url,
                )
                return TelemetryStore(
                    database=str(engine_url),
                    async_writes=False,
                )

            self.logger.debug(
                "Received connection-like store; falling back to database_url"
            )
            return TelemetryStore(database=database_url, async_writes=False)

        self.logger.warning(
            "Unsupported store type %s; falling back to database_url",
            type(candidate),
        )
        # Use DatabaseManager's engine if available (for Cloud SQL)
        try:
            from src.models.database import DatabaseManager

            db = DatabaseManager()
            return get_store(database_url, engine=db.engine)
        except Exception:
            return get_store(database_url)

    def _ensure_base_schema(self) -> None:
        with self._store.connection() as conn:
            _apply_schema(conn, _BASE_SCHEMA)

    @contextmanager
    def _connection(self):
        with self._store.connection() as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def record_discovery_outcome(
        self,
        operation_id: str,
        source_id: str,
        source_name: str,
        source_url: str,
        discovery_result,
    ) -> None:
        """Record detailed discovery outcome for reporting and analysis."""

        from src.utils.discovery_outcomes import DiscoveryResult

        if not isinstance(discovery_result, DiscoveryResult):
            self.logger.warning(
                "Expected DiscoveryResult, got %s", type(discovery_result)
            )
            return

        outcome_data = {
            "operation_id": operation_id,
            "source_id": source_id,
            "source_name": source_name,
            "source_url": source_url,
            "outcome": discovery_result.outcome.value,
            "articles_found": discovery_result.articles_found,
            "articles_new": discovery_result.articles_new,
            "articles_duplicate": discovery_result.articles_duplicate,
            "articles_expired": discovery_result.articles_expired,
            "methods_attempted": ",".join(
                discovery_result.metadata.get("methods_attempted", [])
            ),
            "method_used": discovery_result.method_used,
            "error_details": discovery_result.error_details,
            "http_status": discovery_result.http_status,
            "discovery_time_ms": discovery_result.metadata.get(
                "discovery_time_ms", 0.0
            ),
            "is_success": 1 if discovery_result.is_success else 0,
            "is_content_success": (1 if discovery_result.is_content_success else 0),
            "is_technical_failure": (1 if discovery_result.is_technical_failure else 0),
            "metadata": json.dumps(discovery_result.metadata),
        }

        insert_sql = """
        INSERT INTO discovery_outcomes (
            operation_id,
            source_id,
            source_name,
            source_url,
            outcome,
            articles_found,
            articles_new,
            articles_duplicate,
            articles_expired,
            methods_attempted,
            method_used,
            error_details,
            http_status,
            discovery_time_ms,
            is_success,
            is_content_success,
            is_technical_failure,
            metadata
        ) VALUES (
            :operation_id,
            :source_id,
            :source_name,
            :source_url,
            :outcome,
            :articles_found,
            :articles_new,
            :articles_duplicate,
            :articles_expired,
            :methods_attempted,
            :method_used,
            :error_details,
            :http_status,
            :discovery_time_ms,
            :is_success,
            :is_content_success,
            :is_technical_failure,
            :metadata
        )
        """

        def writer(conn: sqlite3.Connection) -> None:
            retries = 4
            backoff = 0.1
            for attempt in range(retries):
                cursor = conn.cursor()
                try:
                    cursor.execute(insert_sql, outcome_data)
                    return
                except DB_ERRORS as exc:
                    conn.rollback()
                    self.logger.warning(
                        "Database error on discovery outcome write (%d/%d): %s",
                        attempt + 1,
                        retries,
                        exc,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                finally:
                    cursor.close()

            self.logger.error(
                "Failed to record discovery outcome for %s after retries",
                source_name,
            )

        self._store.submit(writer, ensure=_DISCOVERY_OUTCOMES_SCHEMA)

    def get_discovery_outcomes_report(
        self,
        operation_id: str | None = None,
        hours_back: int = 24,
    ) -> dict[str, Any]:
        """Generate a detailed report of discovery outcomes."""

        try:
            where_parts: list[str] = []
            params: dict[str, Any] = {}

            if operation_id:
                where_parts.append("operation_id = :operation_id")
                params["operation_id"] = operation_id
            else:
                where_parts.append(
                    "timestamp >= datetime('now', '-' || :hours_back ||  ' hours')"
                )
                params["hours_back"] = hours_back

            where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

            summary_sql = f"""
            SELECT
                COUNT(*) AS total_sources,
                SUM(is_success) AS technical_success_count,
                SUM(is_content_success) AS content_success_count,
                SUM(is_technical_failure) AS technical_failure_count,
                SUM(articles_found) AS total_articles_found,
                SUM(articles_new) AS total_new_articles,
                SUM(articles_duplicate) AS total_duplicate_articles,
                SUM(articles_expired) AS total_expired_articles,
                AVG(discovery_time_ms) AS avg_discovery_time_ms
            FROM discovery_outcomes
            {where_clause}
            """

            breakdown_sql = f"""
            SELECT outcome, COUNT(*) AS count
            FROM discovery_outcomes
            {where_clause}
            GROUP BY outcome
            ORDER BY count DESC
            """

            top_sources_sql = f"""
            SELECT
                source_name,
                COUNT(*) AS attempts,
                SUM(is_content_success) AS content_successes,
                SUM(articles_new) AS total_new_articles,
                ROUND(
                    SUM(is_content_success) * 100.0 / COUNT(*),
                    2
                ) AS content_success_rate
            FROM discovery_outcomes
            {where_clause}
            GROUP BY source_name
            HAVING attempts >= 1
            ORDER BY content_success_rate DESC, total_new_articles DESC
            LIMIT 10
            """

            with self._connection() as conn:
                summary_row = conn.execute(summary_sql, params).fetchone()
                breakdown_rows = conn.execute(breakdown_sql, params).fetchall()
                top_rows = conn.execute(top_sources_sql, params).fetchall()

            summary = {
                "total_sources": 0,
                "technical_success_count": 0,
                "content_success_count": 0,
                "technical_failure_count": 0,
                "total_articles_found": 0,
                "total_new_articles": 0,
                "total_duplicate_articles": 0,
                "total_expired_articles": 0,
                "avg_discovery_time_ms": 0.0,
            }

            if summary_row:
                for key in summary:
                    summary[key] = summary_row[key] or 0

            total_sources = summary["total_sources"]
            if total_sources:
                technical_rate = (
                    summary["technical_success_count"] / total_sources * 100
                )
                content_rate = summary["content_success_count"] / total_sources * 100
            else:
                technical_rate = 0.0
                content_rate = 0.0

            breakdown = [
                {"outcome": row["outcome"], "count": row["count"]}
                for row in breakdown_rows
            ]

            # Compute percentages client-side to avoid divide-by-zero in SQL
            breakdown_total = sum(item["count"] for item in breakdown) or 1
            for item in breakdown:
                item["percentage"] = round(
                    item["count"] * 100.0 / breakdown_total,
                    2,
                )

            top_performers = []
            for row in top_rows:
                attempts = row["attempts"] or 0
                rate = row["content_success_rate"] or 0.0
                top_performers.append(
                    {
                        "source_name": row["source_name"],
                        "attempts": attempts,
                        "content_successes": row["content_successes"] or 0,
                        "total_new_articles": row["total_new_articles"] or 0,
                        "content_success_rate": rate,
                    }
                )

            return {
                "summary": {
                    **summary,
                    "technical_success_rate": round(technical_rate, 2),
                    "content_success_rate": round(content_rate, 2),
                },
                "outcome_breakdown": breakdown,
                "top_performing_sources": top_performers,
            }

        except Exception as exc:  # pragma: no cover - logged for diagnosis
            self.logger.error(
                "Failed to generate discovery outcomes report: %s",
                exc,
            )
            return {"error": str(exc)}

    @contextmanager
    def track_operation(self, operation_type: OperationType, **kwargs):
        """Context manager for tracking operations."""

        operation_id = str(uuid.uuid4())

        try:
            self.start_operation(operation_id, operation_type, **kwargs)
            yield OperationContext(self, operation_id)
            self.complete_operation(operation_id)
        except Exception as exc:
            self.fail_operation(operation_id, str(exc))
            raise

    def start_operation(
        self,
        operation_id: str,
        operation_type: OperationType,
        **kwargs,
    ) -> None:
        """Start tracking an operation."""

        with self._lock:
            self.active_operations[operation_id] = {
                "operation_type": operation_type,
                "status": OperationStatus.STARTED,
                "start_time": datetime.now(timezone.utc),
                "metrics": OperationMetrics(),
                **kwargs,
            }

        self._update_job_record(
            operation_id,
            OperationStatus.STARTED,
            operation_type=operation_type.value,
            **kwargs,
        )

        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=operation_type,
            status=OperationStatus.STARTED,
            timestamp=datetime.now(timezone.utc),
            message=f"Started {operation_type.value} operation",
            details=kwargs,
        )
        self._send_event(event)

    def update_progress(
        self,
        operation_id: str,
        metrics: OperationMetrics,
    ) -> None:
        """Update operation progress."""

        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id]["metrics"] = metrics
                self.active_operations[operation_id][
                    "status"
                ] = OperationStatus.IN_PROGRESS

        self._update_job_record(
            operation_id,
            OperationStatus.IN_PROGRESS,
            metrics=metrics,
        )

        if self.telemetry_reporter:
            self.telemetry_reporter.send_progress_update(operation_id, metrics)

    def complete_operation(
        self,
        operation_id: str,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        """Mark operation as completed."""

        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id][
                    "status"
                ] = OperationStatus.COMPLETED
                self.active_operations[operation_id]["end_time"] = datetime.now(
                    timezone.utc
                )

        self._update_job_record(
            operation_id,
            OperationStatus.COMPLETED,
            result_summary=result_summary,
        )

        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=self._resolve_operation_type(operation_id),
            status=OperationStatus.COMPLETED,
            timestamp=datetime.now(timezone.utc),
            message="Operation completed successfully",
            details=result_summary or {},
        )
        self._send_event(event)

    def fail_operation(
        self,
        operation_id: str,
        error_message: str,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        """Mark operation as failed."""

        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id]["status"] = OperationStatus.FAILED
                self.active_operations[operation_id]["end_time"] = datetime.now(
                    timezone.utc
                )

        combined_error = {"message": error_message, **(error_details or {})}

        self._update_job_record(
            operation_id,
            OperationStatus.FAILED,
            error_details=combined_error,
        )

        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=self._resolve_operation_type(operation_id),
            status=OperationStatus.FAILED,
            timestamp=datetime.now(timezone.utc),
            message=f"Operation failed: {error_message}",
            error_details=combined_error,
        )
        self._send_event(event)

    def get_operation_status(
        self,
        operation_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            return self.active_operations.get(operation_id)

    def list_active_operations(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {"operation_id": op_id, **details}
                for op_id, details in self.active_operations.items()
                if details["status"]
                in (OperationStatus.STARTED, OperationStatus.IN_PROGRESS)
            ]

    def _update_job_record(
        self,
        operation_id: str,
        status: OperationStatus,
        **kwargs,
    ) -> None:
        """Upsert operation tracking rows with retry handling."""

        operation_type = kwargs.get("operation_type", "")
        if isinstance(operation_type, OperationType):
            operation_type = operation_type.value

        raw_parameters = kwargs.get("parameters") or {}
        parameters = _safe_json_dumps(raw_parameters) or "{}"

        metrics_obj = kwargs.get("metrics")
        metrics_json = _safe_json_dumps(asdict(metrics_obj)) if metrics_obj else None

        error_json = _safe_json_dumps(kwargs.get("error_details"))
        summary_json = _safe_json_dumps(kwargs.get("result_summary"))

        job_defaults = {
            "job_name": kwargs.get("job_name")
            or kwargs.get("operation_name")
            or kwargs.get("source_name")
            or (operation_type or "operation"),
            "params": (
                raw_parameters
                if raw_parameters
                else {
                    k: v
                    for k, v in kwargs.items()
                    if k
                    not in {
                        "metrics",
                        "result_summary",
                        "error_details",
                        "user_id",
                        "session_id",
                        "operation_type",
                    }
                }
            ),
            "commit_sha": kwargs.get("commit_sha"),
            "environment": kwargs.get("environment"),
            "artifact_paths": kwargs.get("artifact_paths"),
            "logs_path": kwargs.get("logs_path"),
        }

        def writer(conn: sqlite3.Connection) -> None:
            retries = 4
            backoff = 0.1
            for attempt in range(retries):
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO jobs (
                            id,
                            job_type,
                            job_name,
                            params,
                            commit_sha,
                            environment,
                            artifact_paths,
                            logs_path
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            operation_id,
                            operation_type or "",
                            job_defaults["job_name"],
                            _safe_json_dumps(job_defaults["params"]),
                            job_defaults["commit_sha"],
                            _safe_json_dumps(job_defaults["environment"]),
                            _safe_json_dumps(job_defaults["artifact_paths"]),
                            job_defaults["logs_path"],
                        ),
                    )

                    cursor.execute(
                        "SELECT 1 FROM operations WHERE id = ?",
                        (operation_id,),
                    )
                    exists = cursor.fetchone() is not None

                    if not exists:
                        cursor.execute(
                            """
                            INSERT INTO operations (
                                id,
                                operation_type,
                                status,
                                user_id,
                                session_id,
                                parameters
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                operation_id,
                                operation_type,
                                status.value,
                                kwargs.get("user_id"),
                                kwargs.get("session_id"),
                                parameters,
                            ),
                        )
                    else:
                        update_fields: list[str] = [
                            "status = ?",
                            "updated_at = CURRENT_TIMESTAMP",
                        ]
                        params: list[Any] = [status.value]

                        if status == OperationStatus.COMPLETED:
                            update_fields.append("completed_at = CURRENT_TIMESTAMP")

                        if metrics_json is not None:
                            update_fields.append("metrics = ?")
                            params.append(metrics_json)

                        if error_json is not None:
                            update_fields.append("error_details = ?")
                            params.append(error_json)

                        if summary_json is not None:
                            update_fields.append("result_summary = ?")
                            params.append(summary_json)

                        params.append(operation_id)

                        cursor.execute(
                            "UPDATE operations SET "
                            + ", ".join(update_fields)
                            + " WHERE id = ?",
                            params,
                        )

                    job_update_fields: list[str] = []
                    job_update_values: list[Any] = []

                    if status == OperationStatus.COMPLETED:
                        job_update_fields.append("finished_at = CURRENT_TIMESTAMP")
                        job_update_fields.append("exit_status = ?")
                        job_update_values.append("success")
                    elif status == OperationStatus.FAILED:
                        job_update_fields.append("finished_at = CURRENT_TIMESTAMP")
                        job_update_fields.append("exit_status = ?")
                        job_update_values.append("failed")
                    elif status == OperationStatus.CANCELLED:
                        job_update_fields.append("finished_at = CURRENT_TIMESTAMP")
                        job_update_fields.append("exit_status = ?")
                        job_update_values.append("cancelled")

                    if metrics_obj is not None:
                        job_update_fields.append("records_processed = ?")
                        job_update_values.append(metrics_obj.processed_items)
                        job_update_fields.append("records_created = ?")
                        job_update_values.append(
                            max(
                                metrics_obj.processed_items - metrics_obj.failed_items,
                                0,
                            )
                        )
                        job_update_fields.append("records_updated = ?")
                        job_update_values.append(0)
                        job_update_fields.append("errors_count = ?")
                        job_update_values.append(metrics_obj.failed_items)

                    if job_update_fields:
                        job_update_values.append(operation_id)
                        cursor.execute(
                            "UPDATE jobs SET "
                            + ", ".join(job_update_fields)
                            + " WHERE id = ?",
                            job_update_values,
                        )

                    return
                except DB_ERRORS as exc:
                    conn.rollback()
                    if _is_missing_table_error(exc):
                        self.logger.warning(
                            "Telemetry store missing operations table; skipping update",
                        )
                        return

                    self.logger.warning(
                        "Database error on operations write (%d/%d): %s",
                        attempt + 1,
                        retries,
                        exc,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                finally:
                    cursor.close()

            self.logger.error(
                "Failed to update operations record for %s after retries",
                operation_id,
            )

        self._store.submit(writer, ensure=_OPERATIONS_SCHEMA)

    def record_site_failure(
        self,
        operation_id: str,
        site_url: str,
        error: Exception,
        site_name: str | None = None,
        discovery_method: str | None = None,
        http_status: int | None = None,
        response_time_ms: float | None = None,
        retry_count: int = 0,
    ):
        """Record a site-specific failure with categorization."""
        failure_type = self.categorize_failure_type(error, http_status)

        site_failure = SiteFailure(
            site_url=site_url,
            site_name=site_name,
            failure_type=failure_type,
            error_message=str(error),
            failure_time=datetime.now(timezone.utc),
            retry_count=retry_count,
            http_status=http_status,
            response_time_ms=response_time_ms,
            discovery_method=discovery_method,
            error_details={
                "exception_type": type(error).__name__,
                "exception_module": type(error).__module__,
                "traceback": str(error),
            },
        )

        # Update operation metrics
        with self._lock:
            if operation_id in self.active_operations:
                op = self.active_operations[operation_id]
                metrics = op.get("metrics", OperationMetrics())
                if metrics.site_failures is None:
                    metrics.site_failures = []
                metrics.site_failures.append(site_failure)
                metrics.failed_sites += 1
                metrics.failed_items += 1
                op["metrics"] = metrics

        # Log the failure
        self.logger.warning(
            f"Site failure [{failure_type.value}] for {site_url}: {error}"
        )

    def categorize_failure_type(
        self, error: Exception, http_status: int | None = None
    ) -> FailureType:
        """Categorize the type of failure based on error and context."""
        error_str = str(error).lower()

        # Network-related errors
        if any(keyword in error_str for keyword in _NETWORK_ERROR_KEYWORDS):
            return FailureType.NETWORK_ERROR

        # SSL/TLS errors
        if any(keyword in error_str for keyword in _SSL_ERROR_KEYWORDS):
            return FailureType.SSL_ERROR

        # Timeout errors
        if any(keyword in error_str for keyword in _TIMEOUT_KEYWORDS):
            return FailureType.TIMEOUT

        # Cloudflare protection
        if any(
            keyword in error_str
            for keyword in [
                "cloudflare",
                "checking your browser",
                "ddos protection",
                "503 service temporarily unavailable",
            ]
        ):
            return FailureType.CLOUDFLARE_PROTECTION

        # Rate limiting
        if any(keyword in error_str for keyword in _RATE_LIMIT_KEYWORDS) or (
            http_status == 429
        ):
            return FailureType.RATE_LIMITED

        # Authentication errors
        if any(keyword in error_str for keyword in _AUTH_ERROR_KEYWORDS) or (
            http_status in {401, 403}
        ):
            return FailureType.AUTHENTICATION_ERROR

        # HTTP status code errors
        if http_status is not None:
            if 400 <= http_status < 500:
                return FailureType.HTTP_ERROR
            elif 500 <= http_status < 600:
                return FailureType.HTTP_ERROR

        # Parsing/content errors
        if any(
            keyword in error_str
            for keyword in [
                "parse",
                "parsing",
                "invalid",
                "malformed",
                "decode",
                "encoding",
                "html",
                "xml",
                "feed",
            ]
        ):
            if "feed" in error_str or "rss" in error_str:
                return FailureType.RSS_ERROR
            return FailureType.PARSING_ERROR

        # Content-related errors
        if any(
            keyword in error_str
            for keyword in ["content", "empty", "no articles", "no data"]
        ):
            return FailureType.CONTENT_ERROR

        return FailureType.UNKNOWN

    def get_site_failures(self, operation_id: str) -> list[SiteFailure]:
        """Get all site failures for an operation."""
        with self._lock:
            if operation_id in self.active_operations:
                metrics = self.active_operations[operation_id].get("metrics")
                if metrics and metrics.site_failures:
                    return metrics.site_failures[:]
        return []

    def get_failure_summary(self, operation_id: str) -> dict[str, Any]:
        """Get a summary of failures for an operation."""
        failures = self.get_site_failures(operation_id)

        if not failures:
            return {
                "total_failures": 0,
                "failure_types": {},
                "failed_sites": [],
            }

        # Count failures by type
        failure_counts: dict[str, int] = {}
        for failure in failures:
            failure_type = failure.failure_type.value
            failure_counts[failure_type] = failure_counts.get(failure_type, 0) + 1

        # Get failed site URLs
        failed_sites = [failure.site_url for failure in failures]

        # Calculate retry statistics
        total_retries = sum(failure.retry_count for failure in failures)
        avg_retries = total_retries / len(failures) if failures else 0

        most_common = None
        if failure_counts:
            most_common = max(
                failure_counts.items(),
                key=lambda item: item[1],
            )[0]

        return {
            "total_failures": len(failures),
            "failure_types": failure_counts,
            "failed_sites": failed_sites,
            "total_retries": total_retries,
            "average_retries": avg_retries,
            "most_common_failure": most_common,
        }

    def identify_common_failures(
        self,
        operation_id: str,
    ) -> list[dict[str, Any]]:
        """Identify patterns in failures for debugging."""
        failures = self.get_site_failures(operation_id)

        if not failures:
            return []

        # Group by failure type and error message patterns
        patterns = {}
        for failure in failures:
            key = f"{failure.failure_type.value}|{failure.error_message[:100]}"
            if key not in patterns:
                patterns[key] = {
                    "failure_type": failure.failure_type.value,
                    "error_pattern": failure.error_message[:100],
                    "count": 0,
                    "sites": [],
                    "avg_response_time": 0,
                    "http_statuses": set(),
                }

            pattern = patterns[key]
            pattern["count"] += 1
            pattern["sites"].append(failure.site_url)

            if failure.response_time_ms:
                current_avg = pattern["avg_response_time"]
                count = pattern["count"]
                weighted_total = current_avg * (count - 1) + failure.response_time_ms
                pattern["avg_response_time"] = weighted_total / count

            if failure.http_status:
                pattern["http_statuses"].add(failure.http_status)

        # Convert to list and sort by count
        common_patterns = []
        for pattern in patterns.values():
            pattern["http_statuses"] = list(pattern["http_statuses"])
            common_patterns.append(pattern)

        return sorted(common_patterns, key=lambda x: x["count"], reverse=True)

    def generate_failure_report(self, operation_id: str) -> str:
        """Generate a human-readable failure report."""
        summary = self.get_failure_summary(operation_id)
        common_failures = self.identify_common_failures(operation_id)

        if summary["total_failures"] == 0:
            return "No failures detected in this operation."

        report = []
        report.append(f"=== Failure Report for Operation {operation_id} ===")
        report.append(f"Total failures: {summary['total_failures']}")

        if summary["most_common_failure"]:
            report.append(f"Most common failure type: {summary['most_common_failure']}")

        report.append(f"Total retries attempted: {summary['total_retries']}")
        report.append(f"Average retries per failure: {summary['average_retries']:.1f}")

        report.append("\n--- Failure Breakdown by Type ---")
        for failure_type, count in summary["failure_types"].items():
            percentage = (count / summary["total_failures"]) * 100
            report.append(f"{failure_type}: {count} ({percentage:.1f}%)")

        if common_failures:
            report.append("\n--- Common Failure Patterns ---")
            for i, pattern in enumerate(common_failures[:5], 1):
                pattern_header = (
                    f"{i}. {pattern['failure_type']} ({pattern['count']} sites)"
                )
                report.append(pattern_header)
                report.append(f"   Error: {pattern['error_pattern']}")
                if pattern["avg_response_time"] > 0:
                    report.append(
                        f"   Avg response time: {pattern['avg_response_time']:.0f}ms"
                    )
                if pattern["http_statuses"]:
                    report.append(f"   HTTP statuses: {pattern['http_statuses']}")
                report.append("")

        return "\n".join(report)

    def track_http_status(
        self,
        operation_id: str,
        source_id: str,
        source_url: str,
        discovery_method: DiscoveryMethod,
        attempted_url: str,
        status_code: int,
        response_time_ms: float,
        error_message: str | None = None,
        content_length: int | None = None,
    ):
        """Track HTTP status codes for discovery methods."""
        # Categorize status code
        if 200 <= status_code < 300:
            category = HTTPStatusCategory.SUCCESS
        elif 300 <= status_code < 400:
            category = HTTPStatusCategory.REDIRECT
        elif 400 <= status_code < 500:
            category = HTTPStatusCategory.CLIENT_ERROR
        elif 500 <= status_code < 600:
            category = HTTPStatusCategory.SERVER_ERROR
        else:
            category = HTTPStatusCategory.CLIENT_ERROR  # Default fallback

        status_tracking = HTTPStatusTracking(
            source_id=source_id,
            source_url=source_url,
            discovery_method=discovery_method,
            attempted_url=attempted_url,
            status_code=status_code,
            status_category=category,
            response_time_ms=response_time_ms,
            timestamp=datetime.now(timezone.utc),
            operation_id=operation_id,
            error_message=error_message,
            content_length=content_length,
        )

        # Store in database
        self._store_http_status_tracking(status_tracking)

        # Log significant status codes
        if status_code >= 400:
            self.logger.warning(
                f"HTTP {status_code} for {discovery_method.value} on "
                f"{source_url} -> {attempted_url}"
            )

    def update_discovery_method_effectiveness(
        self,
        source_id: str,
        source_url: str,
        discovery_method: DiscoveryMethod,
        status: DiscoveryMethodStatus,
        articles_found: int,
        response_time_ms: float,
        status_codes: list[int],
        notes: str | None = None,
    ):
        """Update the effectiveness tracking for a discovery method."""
        effectiveness = self._get_or_create_method_effectiveness(
            source_id, source_url, discovery_method
        )

        previous_attempts = effectiveness.attempt_count
        previous_success_rate = effectiveness.success_rate
        previous_avg_response_time = effectiveness.avg_response_time_ms

        # Update statistics
        effectiveness.attempt_count += 1
        effectiveness.last_attempt = datetime.now(timezone.utc)
        effectiveness.status = status
        effectiveness.articles_found = max(
            effectiveness.articles_found,
            articles_found,
        )

        # Calculate rolling average response time
        previous_total_time = previous_avg_response_time * previous_attempts
        total_time = previous_total_time + response_time_ms
        effectiveness.avg_response_time_ms = total_time / max(
            1, effectiveness.attempt_count
        )

        # Update success rate
        if status == DiscoveryMethodStatus.SUCCESS and articles_found > 0:
            success_estimate = (
                effectiveness.attempt_count * effectiveness.success_rate / 100
            )
            success_count = max(1, success_estimate)
            effectiveness.success_rate = (
                success_count / effectiveness.attempt_count
            ) * 100
        elif status == DiscoveryMethodStatus.SKIPPED:
            effectiveness.success_rate = previous_success_rate
        else:
            # Decay success rate if this attempt failed
            decay_factor = (
                effectiveness.attempt_count - 1
            ) / effectiveness.attempt_count
            effectiveness.success_rate *= decay_factor

        # Update recent status codes (keep last 10)
        effectiveness.last_status_codes.extend(status_codes)
        effectiveness.last_status_codes = effectiveness.last_status_codes[-10:]

        if notes:
            effectiveness.notes = notes

        # Store in database
        self._store_method_effectiveness(effectiveness)

    def get_effective_discovery_methods(
        self,
        source_id: str,
    ) -> list[DiscoveryMethod]:
        """Get list of discovery methods that work well for a source."""
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT discovery_method,
                           success_rate,
                           articles_found,
                           attempt_count,
                           status
                    FROM discovery_method_effectiveness
                    WHERE source_id = :source_id
                    ORDER BY success_rate DESC, articles_found DESC
                    """,
                    {"source_id": source_id},
                )

                effective_methods: list[DiscoveryMethod] = []
                for row in cursor.fetchall():
                    success_rate = row["success_rate"] or 0
                    articles = row["articles_found"] or 0
                    attempts = row["attempt_count"] or 0

                    if success_rate > 50 and articles > 0 and attempts >= 2:
                        try:
                            method = DiscoveryMethod(row["discovery_method"])
                        except ValueError:
                            continue
                        effective_methods.append(method)

                return effective_methods

        except Exception as exc:
            self.logger.error("Failed to get effective methods: %s", exc)

        # Return all methods as fallback
        return [
            DiscoveryMethod.RSS_FEED,
            DiscoveryMethod.NEWSPAPER4K,
            DiscoveryMethod.STORYSNIFFER,
        ]

    def _store_http_status_tracking(self, tracking: HTTPStatusTracking):
        """Store HTTP status tracking in database."""
        payload = {
            "source_id": tracking.source_id,
            "source_url": tracking.source_url,
            "discovery_method": tracking.discovery_method.value,
            "attempted_url": tracking.attempted_url,
            "status_code": tracking.status_code,
            "status_category": tracking.status_category.value,
            "response_time_ms": tracking.response_time_ms,
            "timestamp": _format_timestamp(tracking.timestamp),
            "operation_id": tracking.operation_id,
            "error_message": tracking.error_message,
            "content_length": tracking.content_length,
        }

        def writer(conn: sqlite3.Connection) -> None:
            retries = 3
            backoff = 0.1
            for attempt in range(retries):
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        """
                        INSERT INTO http_status_tracking (
                            source_id,
                            source_url,
                            discovery_method,
                            attempted_url,
                            status_code,
                            status_category,
                            response_time_ms,
                            timestamp,
                            operation_id,
                            error_message,
                            content_length
                        ) VALUES (
                            :source_id,
                            :source_url,
                            :discovery_method,
                            :attempted_url,
                            :status_code,
                            :status_category,
                            :response_time_ms,
                            :timestamp,
                            :operation_id,
                            :error_message,
                            :content_length
                        )
                        """,
                        payload,
                    )
                    return
                except DB_ERRORS as exc:
                    conn.rollback()
                    if _is_missing_table_error(exc):
                        self.logger.warning(
                            "Telemetry store missing http_status_tracking table; "
                            "skipping write",
                        )
                        return

                    self.logger.warning(
                        "Database error on http_status insert (%d/%d): %s",
                        attempt + 1,
                        retries,
                        exc,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                finally:
                    cursor.close()

            self.logger.error(
                "Failed to store HTTP status tracking for %s after retries",
                tracking.source_id,
            )

        self._store.submit(writer, ensure=_HTTP_STATUS_SCHEMA)

    def _get_or_create_method_effectiveness(
        self,
        source_id: str,
        source_url: str,
        discovery_method: DiscoveryMethod,
    ) -> DiscoveryMethodEffectiveness:
        """Get existing or create new method effectiveness record."""
        try:
            with self._connection() as conn:
                row = conn.execute(
                    """
                    SELECT
                        source_id,
                        source_url,
                        discovery_method,
                        status,
                        articles_found,
                        success_rate,
                        last_attempt,
                        attempt_count,
                        avg_response_time_ms,
                        last_status_codes,
                        notes
                    FROM discovery_method_effectiveness
                    WHERE source_id = :source_id
                    AND discovery_method = :discovery_method
                    """,
                    {
                        "source_id": source_id,
                        "discovery_method": discovery_method.value,
                    },
                ).fetchone()

                if row:
                    return DiscoveryMethodEffectiveness(
                        source_id=row["source_id"],
                        source_url=row["source_url"],
                        discovery_method=DiscoveryMethod(row["discovery_method"]),
                        status=DiscoveryMethodStatus(row["status"]),
                        articles_found=row["articles_found"],
                        success_rate=row["success_rate"],
                        last_attempt=_parse_timestamp(row["last_attempt"]),
                        attempt_count=row["attempt_count"],
                        avg_response_time_ms=row["avg_response_time_ms"],
                        last_status_codes=json.loads(row["last_status_codes"] or "[]"),
                        notes=row["notes"],
                    )
        except Exception as exc:
            self.logger.error(
                "Failed to get method effectiveness for %s: %s",
                source_id,
                exc,
            )

        # Create new record
        return DiscoveryMethodEffectiveness(
            source_id=source_id,
            source_url=source_url,
            discovery_method=discovery_method,
            status=DiscoveryMethodStatus.SUCCESS,
            articles_found=0,
            success_rate=0.0,
            last_attempt=datetime.now(timezone.utc),
            attempt_count=0,
            avg_response_time_ms=0.0,
            last_status_codes=[],
        )

    def _store_method_effectiveness(
        self,
        effectiveness: DiscoveryMethodEffectiveness,
    ):
        """Store or update method effectiveness in database."""
        payload = {
            "source_id": effectiveness.source_id,
            "source_url": effectiveness.source_url,
            "discovery_method": effectiveness.discovery_method.value,
            "status": effectiveness.status.value,
            "articles_found": effectiveness.articles_found,
            "success_rate": effectiveness.success_rate,
            "last_attempt": _format_timestamp(effectiveness.last_attempt),
            "attempt_count": effectiveness.attempt_count,
            "avg_response_time_ms": effectiveness.avg_response_time_ms,
            "last_status_codes": json.dumps(effectiveness.last_status_codes),
            "notes": effectiveness.notes,
        }

        def writer(conn: sqlite3.Connection) -> None:
            retries = 3
            backoff = 0.1
            for attempt in range(retries):
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        """
                        UPDATE discovery_method_effectiveness
                        SET status = :status,
                            articles_found = :articles_found,
                            success_rate = :success_rate,
                            last_attempt = :last_attempt,
                            attempt_count = :attempt_count,
                            avg_response_time_ms = :avg_response_time_ms,
                            last_status_codes = :last_status_codes,
                            notes = :notes
                        WHERE source_id = :source_id
                        AND discovery_method = :discovery_method
                        """,
                        payload,
                    )

                    if cursor.rowcount == 0:
                        cursor.execute(
                            """
                            INSERT INTO discovery_method_effectiveness (
                                source_id,
                                source_url,
                                discovery_method,
                                status,
                                articles_found,
                                success_rate,
                                last_attempt,
                                attempt_count,
                                avg_response_time_ms,
                                last_status_codes,
                                notes
                            ) VALUES (
                                :source_id,
                                :source_url,
                                :discovery_method,
                                :status,
                                :articles_found,
                                :success_rate,
                                :last_attempt,
                                :attempt_count,
                                :avg_response_time_ms,
                                :last_status_codes,
                                :notes
                            )
                            """,
                            payload,
                        )

                    return
                except DB_ERRORS as exc:
                    conn.rollback()
                    if _is_missing_table_error(exc):
                        self.logger.warning(
                            "Telemetry store missing method effectiveness table; "
                            "skipping upsert",
                        )
                        return

                    self.logger.warning(
                        "Database error on method upsert (%d/%d): %s",
                        attempt + 1,
                        retries,
                        exc,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                finally:
                    cursor.close()

            self.logger.error(
                "Failed to store method effectiveness for %s after retries",
                effectiveness.source_id,
            )

        self._store.submit(writer, ensure=_DISCOVERY_METHOD_SCHEMA)

    def _send_event(self, event: OperationEvent):
        """Send event to telemetry system."""
        if self.telemetry_reporter:
            self.telemetry_reporter.send_operation_event(event)


class OperationContext:
    """Context object for operation tracking."""

    def __init__(self, tracker: OperationTracker, operation_id: str):
        self.tracker = tracker
        self.operation_id = operation_id
        self.start_time = time.time()
        self.last_update = time.time()

    def update_progress(
        self,
        processed: int | OperationMetrics,
        total: int | None = None,
        message: str = "",
    ):
        """Update operation progress.

        Supports both legacy positional usage (processed, total, message) and
        passing an ``OperationMetrics`` instance directly.
        """

        current_time = time.time()

        if isinstance(processed, OperationMetrics):
            metrics = processed

            if isinstance(total, str) and not message:
                message = total
                total = None

            if isinstance(total, int) and total >= 0 and metrics.total_items == 0:
                metrics.total_items = total

            if (
                metrics.total_items > 0
                and metrics.processed_items >= 0
                and metrics.success_rate == 0.0
            ):
                metrics.success_rate = (
                    metrics.processed_items / metrics.total_items * 100
                )

            elapsed = current_time - self.start_time
            if elapsed > 0 and metrics.items_per_second == 0.0:
                metrics.items_per_second = metrics.processed_items / elapsed

            if (
                metrics.items_per_second > 0
                and metrics.total_items > metrics.processed_items
                and metrics.estimated_completion is None
            ):
                remaining_items = metrics.total_items - metrics.processed_items
                remaining_seconds = remaining_items / metrics.items_per_second
                metrics.estimated_completion = datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() + remaining_seconds,
                    timezone.utc,
                )
        else:
            if total is None:
                raise TypeError("total must be provided when processed is an int")

            elapsed = current_time - self.start_time
            success_rate = (processed / total * 100) if total > 0 else 0
            items_per_second = processed / elapsed if elapsed > 0 else 0

            estimated_completion = None
            if items_per_second > 0 and total > processed:
                remaining_items = total - processed
                remaining_seconds = remaining_items / items_per_second
                estimated_completion = datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() + remaining_seconds,
                    timezone.utc,
                )

            metrics = OperationMetrics(
                total_items=total,
                processed_items=processed,
                success_rate=success_rate,
                items_per_second=items_per_second,
                estimated_completion=estimated_completion,
            )

        self.tracker.update_progress(self.operation_id, metrics)
        self.last_update = current_time

        if message:
            self.tracker.logger.info(
                "Operation %s: %s",
                self.operation_id,
                message,
            )

    def log_message(self, message: str, level: str = "info"):
        """Log a message for this operation."""
        logger = self.tracker.logger
        getattr(logger, level)(f"Operation {self.operation_id}: {message}")


def create_telemetry_system(
    database_url: str | None = None,
    *,
    api_base_url: str | None = None,
    api_key: str | None = None,
    store: TelemetryStore | None = None,
) -> OperationTracker:
    """Factory function to create telemetry system."""
    # If no database_url provided, use DatabaseManager to get Cloud SQL connection
    if database_url is None:
        from src.models.database import DatabaseManager

        db = DatabaseManager()
        database_url = str(db.engine.url)

    reporter = None
    if api_base_url:
        reporter = TelemetryReporter(api_base_url, api_key)

    return OperationTracker(
        store=store,
        telemetry_reporter=reporter,
        database_url=database_url,
    )
