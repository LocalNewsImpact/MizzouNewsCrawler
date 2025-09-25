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
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import text
import sqlite3
from functools import wraps


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


@dataclass
class OperationMetrics:
    """Metrics for tracking operation progress."""

    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    success_rate: float = 0.0
    items_per_second: float = 0.0
    estimated_completion: Optional[datetime] = None
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    # Site-specific failure tracking
    failed_sites: int = 0
    site_failures: Optional[List["SiteFailure"]] = None

    def __post_init__(self):
        if self.site_failures is None:
            self.site_failures = []


@dataclass
class SiteFailure:
    """Details about a site-specific failure."""

    site_url: str
    site_name: Optional[str]
    failure_type: FailureType
    error_message: str
    failure_time: datetime
    retry_count: int = 0
    http_status: Optional[int] = None
    response_time_ms: Optional[float] = None
    discovery_method: Optional[str] = None  # RSS, newspaper4k, storysniffer
    error_details: Optional[Dict[str, Any]] = None

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
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    message: str = ""
    details: Optional[Dict[str, Any]] = None
    metrics: Optional[OperationMetrics] = None
    error_details: Optional[Dict[str, Any]] = None

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
    error_message: Optional[str] = None
    content_length: Optional[int] = None

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
    last_status_codes: List[int]  # Recent status codes
    notes: Optional[str] = None

    def __post_init__(self):
        if self.last_attempt is None:
            self.last_attempt = datetime.now(timezone.utc)
        if not self.last_status_codes:
            self.last_status_codes = []


class TelemetryReporter:
    """Handles sending telemetry data to external APIs."""

    def __init__(
        self, api_base_url: Optional[str] = None, api_key: Optional[str] = None
    ):
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

    def _serialize_event(self, event: OperationEvent) -> Dict[str, Any]:
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
        self, db_engine, telemetry_reporter: Optional[TelemetryReporter] = None
    ):
        self.db_engine = db_engine
        self.telemetry_reporter = telemetry_reporter
        self.logger = logging.getLogger(__name__)
        self.active_operations: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # Ensure telemetry operations table exists
        self._create_operations_table()
        self._create_tracking_tables()

    def _create_operations_table(self):
        """Create operations table for telemetry tracking."""
        create_table_sql = """
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
        """

        with self.db_engine.connect() as conn:
            conn.execute(text(create_table_sql))
            conn.commit()

    def _create_tracking_tables(self):
        """Create tables for HTTP status and discovery method tracking."""

        # HTTP status tracking table
        http_status_table_sql = """
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
        """

        # Discovery method effectiveness table
        effectiveness_table_sql = """
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
        """

        # Index creation statements
        http_status_indexes = [
            (
                "CREATE INDEX IF NOT EXISTS idx_http_source_method "
                "ON http_status_tracking (source_id, discovery_method)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_http_status_code "
                "ON http_status_tracking (status_code)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_http_timestamp "
                "ON http_status_tracking (timestamp)"
            ),
        ]

        effectiveness_indexes = [
            (
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_effectiveness_source_method "
                "ON discovery_method_effectiveness "
                "(source_id, discovery_method)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_effectiveness_source "
                "ON discovery_method_effectiveness (source_id)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_effectiveness_method "
                "ON discovery_method_effectiveness (discovery_method)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS "
                "idx_effectiveness_success_rate "
                "ON discovery_method_effectiveness (success_rate)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS "
                "idx_effectiveness_last_attempt "
                "ON discovery_method_effectiveness (last_attempt)"
            ),
        ]

        with self.db_engine.connect() as conn:
            # Create tables
            conn.execute(text(http_status_table_sql))
            conn.execute(text(effectiveness_table_sql))

            # Create indexes
            for index_sql in http_status_indexes:
                conn.execute(text(index_sql))
            for index_sql in effectiveness_indexes:
                conn.execute(text(index_sql))

            conn.commit()

        # Create discovery outcomes table
        self._create_discovery_outcomes_table()

    def _create_discovery_outcomes_table(self):
        """Create table for storing detailed discovery outcomes."""
        create_table_sql = """
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
        """

        # Create indexes for efficient querying
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_discovery_operation ON discovery_outcomes (operation_id)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_source ON discovery_outcomes (source_id)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_outcome ON discovery_outcomes (outcome)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_success ON discovery_outcomes (is_success)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_content_success ON discovery_outcomes (is_content_success)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_timestamp ON discovery_outcomes (timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_source_outcome ON discovery_outcomes (source_id, outcome)",
        ]

        with self.db_engine.connect() as conn:
            conn.execute(text(create_table_sql))
            for index_sql in indexes:
                conn.execute(text(index_sql))
            conn.commit()

    def record_discovery_outcome(self, operation_id: str, source_id: str, source_name: str, 
                                source_url: str, discovery_result):
        """Record detailed discovery outcome for reporting and analysis."""
        from src.utils.discovery_outcomes import DiscoveryResult
        
        if not isinstance(discovery_result, DiscoveryResult):
            self.logger.warning(f"Expected DiscoveryResult, got {type(discovery_result)}")
            return

        try:
            # Convert DiscoveryResult to database record
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
                "methods_attempted": ",".join(discovery_result.metadata.get("methods_attempted", [])),
                "method_used": discovery_result.method_used,
                "error_details": discovery_result.error_details,
                "http_status": discovery_result.http_status,
                "discovery_time_ms": discovery_result.metadata.get("discovery_time_ms", 0.0),
                "is_success": 1 if discovery_result.is_success else 0,
                "is_content_success": 1 if discovery_result.is_content_success else 0,
                "is_technical_failure": 1 if discovery_result.is_technical_failure else 0,
                "metadata": json.dumps(discovery_result.metadata),
            }

            insert_sql = """
            INSERT INTO discovery_outcomes (
                operation_id, source_id, source_name, source_url, outcome,
                articles_found, articles_new, articles_duplicate, articles_expired,
                methods_attempted, method_used, error_details, http_status,
                discovery_time_ms, is_success, is_content_success, is_technical_failure,
                metadata
            ) VALUES (
                :operation_id, :source_id, :source_name, :source_url, :outcome,
                :articles_found, :articles_new, :articles_duplicate, :articles_expired,
                :methods_attempted, :method_used, :error_details, :http_status,
                :discovery_time_ms, :is_success, :is_content_success, :is_technical_failure,
                :metadata
            )
            """

            with self.db_engine.connect() as conn:
                conn.execute(text(insert_sql), outcome_data)
                
                # Update discovery_attempted timestamp in sources table
                # This ensures sources are marked as attempted even if they failed
                sources_update_sql = """
                UPDATE sources 
                SET discovery_attempted = CURRENT_TIMESTAMP 
                WHERE id = :source_id
                """
                conn.execute(text(sources_update_sql), {"source_id": source_id})
                
                conn.commit()

            self.logger.debug(f"Recorded discovery outcome for {source_name}: {discovery_result.outcome.value}")

        except Exception as e:
            self.logger.error(f"Failed to record discovery outcome for {source_name}: {e}")

    def get_discovery_outcomes_report(self, operation_id: Optional[str] = None, 
                                    hours_back: int = 24) -> Dict[str, Any]:
        """Generate a detailed report of discovery outcomes."""
        try:
            # Base query
            where_clauses = []
            params = {}

            if operation_id:
                where_clauses.append("operation_id = :operation_id")
                params["operation_id"] = operation_id
            else:
                where_clauses.append("timestamp >= datetime('now', '-' || :hours_back || ' hours')")
                params["hours_back"] = hours_back

            where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            # Summary query
            summary_sql = f"""
            SELECT 
                COUNT(*) as total_sources,
                SUM(is_success) as technical_success_count,
                SUM(is_content_success) as content_success_count,
                SUM(is_technical_failure) as technical_failure_count,
                SUM(articles_found) as total_articles_found,
                SUM(articles_new) as total_new_articles,
                SUM(articles_duplicate) as total_duplicate_articles,
                SUM(articles_expired) as total_expired_articles,
                AVG(discovery_time_ms) as avg_discovery_time_ms
            FROM discovery_outcomes 
            {where_clause}
            """

            # Outcome breakdown query  
            breakdown_sql = f"""
            SELECT 
                outcome,
                COUNT(*) as count,
                ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM discovery_outcomes {where_clause}), 2) as percentage
            FROM discovery_outcomes 
            {where_clause}
            GROUP BY outcome
            ORDER BY count DESC
            """

            # Top performing sources
            top_sources_sql = f"""
            SELECT 
                source_name,
                COUNT(*) as attempts,
                SUM(is_content_success) as content_successes,
                SUM(articles_new) as total_new_articles,
                ROUND(SUM(is_content_success) * 100.0 / COUNT(*), 2) as content_success_rate
            FROM discovery_outcomes 
            {where_clause}
            GROUP BY source_name
            HAVING attempts >= 1
            ORDER BY content_success_rate DESC, total_new_articles DESC
            LIMIT 10
            """

            with self.db_engine.connect() as conn:
                # Get summary
                summary_result = conn.execute(text(summary_sql), params).fetchone()
                
                # Get breakdown
                breakdown_results = conn.execute(text(breakdown_sql), params).fetchall()
                
                # Get top sources
                top_sources_results = conn.execute(text(top_sources_sql), params).fetchall()

                # Calculate rates
                total_sources = summary_result[0] if summary_result[0] else 1
                technical_success_rate = (summary_result[1] / total_sources * 100) if total_sources > 0 else 0
                content_success_rate = (summary_result[2] / total_sources * 100) if total_sources > 0 else 0

                return {
                    "summary": {
                        "total_sources": summary_result[0],
                        "technical_success_count": summary_result[1],
                        "content_success_count": summary_result[2], 
                        "technical_failure_count": summary_result[3],
                        "total_articles_found": summary_result[4],
                        "total_new_articles": summary_result[5],
                        "total_duplicate_articles": summary_result[6],
                        "total_expired_articles": summary_result[7],
                        "avg_discovery_time_ms": summary_result[8],
                        "technical_success_rate": round(technical_success_rate, 2),
                        "content_success_rate": round(content_success_rate, 2),
                    },
                    "outcome_breakdown": [
                        {
                            "outcome": row[0],
                            "count": row[1], 
                            "percentage": row[2]
                        } for row in breakdown_results
                    ],
                    "top_performing_sources": [
                        {
                            "source_name": row[0],
                            "attempts": row[1],
                            "content_successes": row[2],
                            "total_new_articles": row[3],
                            "content_success_rate": row[4]
                        } for row in top_sources_results
                    ]
                }

        except Exception as e:
            self.logger.error(f"Failed to generate discovery outcomes report: {e}")
            return {"error": str(e)}

    @contextmanager
    def track_operation(self, operation_type: OperationType, **kwargs):
        """Context manager for tracking operations."""
        operation_id = str(uuid.uuid4())

        try:
            # Start tracking
            self.start_operation(operation_id, operation_type, **kwargs)

            # Yield tracker for updates
            yield OperationContext(self, operation_id)

            # Mark as completed
            self.complete_operation(operation_id)

        except Exception as e:
            # Mark as failed
            self.fail_operation(operation_id, str(e))
            raise

    def start_operation(
        self, operation_id: str, operation_type: OperationType, **kwargs
    ):
        """Start tracking an operation."""
        with self._lock:
            self.active_operations[operation_id] = {
                "operation_type": operation_type,
                "status": OperationStatus.STARTED,
                "start_time": datetime.now(timezone.utc),
                "metrics": OperationMetrics(),
                **kwargs,
            }

        # Create database record
        self._update_job_record(operation_id, OperationStatus.STARTED, **kwargs)

        # Send telemetry event
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

    def update_progress(self, operation_id: str, metrics: OperationMetrics):
        """Update operation progress."""
        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id]["metrics"] = metrics
                self.active_operations[operation_id][
                    "status"
                ] = OperationStatus.IN_PROGRESS

        # Update database
        self._update_job_record(
            operation_id, OperationStatus.IN_PROGRESS, metrics=metrics
        )

        # Send progress update
        if self.telemetry_reporter:
            self.telemetry_reporter.send_progress_update(operation_id, metrics)

    def complete_operation(
        self, operation_id: str, result_summary: Optional[Dict[str, Any]] = None
    ):
        """Mark operation as completed."""
        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id][
                    "status"
                ] = OperationStatus.COMPLETED
                self.active_operations[operation_id]["end_time"] = datetime.now(
                    timezone.utc
                )

        # Update database
        self._update_job_record(
            operation_id, OperationStatus.COMPLETED, result_summary=result_summary
        )

        # Send completion event
        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=self.active_operations.get(operation_id, {}).get(
                "operation_type"
            ),
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
        error_details: Optional[Dict[str, Any]] = None,
    ):
        """Mark operation as failed."""
        with self._lock:
            if operation_id in self.active_operations:
                self.active_operations[operation_id]["status"] = OperationStatus.FAILED
                self.active_operations[operation_id]["end_time"] = datetime.now(
                    timezone.utc
                )

        # Update database
        self._update_job_record(
            operation_id,
            OperationStatus.FAILED,
            error_details={"message": error_message, **(error_details or {})},
        )

        # Send failure event
        event = OperationEvent(
            event_id=str(uuid.uuid4()),
            operation_id=operation_id,
            operation_type=self.active_operations.get(operation_id, {}).get(
                "operation_type"
            ),
            status=OperationStatus.FAILED,
            timestamp=datetime.now(timezone.utc),
            message=f"Operation failed: {error_message}",
            error_details={"message": error_message, **(error_details or {})},
        )
        self._send_event(event)

    def get_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of an operation."""
        with self._lock:
            return self.active_operations.get(operation_id)

    def list_active_operations(self) -> List[Dict[str, Any]]:
        """List all active operations."""
        with self._lock:
            return [
                {"operation_id": op_id, **details}
                for op_id, details in self.active_operations.items()
                if details["status"]
                in [OperationStatus.STARTED, OperationStatus.IN_PROGRESS]
            ]

    def _update_job_record(self, operation_id: str, status: OperationStatus, **kwargs):
        """Update operation record in database.

        Retries on sqlite3.OperationalError (database is locked) a few
        times with exponential backoff to reduce transient lock failures.
        """

        @wraps(self._update_job_record)
        def _inner_update():
            # Check if record exists
            with self.db_engine.connect() as conn:
                result = conn.execute(
                    text("SELECT id FROM operations WHERE id = :id"),
                    {"id": operation_id},
                )
                exists = result.fetchone() is not None

            if not exists:
                # Insert new record
                insert_sql = """
                INSERT INTO operations (id, operation_type, status, 
                                      user_id, session_id, parameters)
                VALUES (:id, :operation_type, :status, 
                        :user_id, :session_id, :parameters)
                """
                with self.db_engine.connect() as conn:
                    conn.execute(
                        text(insert_sql),
                        {
                            "id": operation_id,
                            "operation_type": kwargs.get("operation_type", ""),
                            "status": status.value,
                            "user_id": kwargs.get("user_id"),
                            "session_id": kwargs.get("session_id"),
                            "parameters": json.dumps(kwargs.get("parameters", {})),
                        },
                    )
                    conn.commit()
            else:
                # Update existing record
                update_fields = ["status = :status", "updated_at = CURRENT_TIMESTAMP"]
                params = {"id": operation_id, "status": status.value}

                if status == OperationStatus.COMPLETED:
                    update_fields.append("completed_at = CURRENT_TIMESTAMP")

                if "metrics" in kwargs and kwargs["metrics"]:
                    update_fields.append("metrics = :metrics")
                    params["metrics"] = json.dumps(asdict(kwargs["metrics"]))

                if "error_details" in kwargs:
                    update_fields.append("error_details = :error_details")
                    params["error_details"] = json.dumps(kwargs["error_details"])

                if "result_summary" in kwargs:
                    update_fields.append("result_summary = :result_summary")
                    params["result_summary"] = json.dumps(kwargs["result_summary"])

                update_sql = (
                    f"UPDATE operations SET {', '.join(update_fields)} "
                    f"WHERE id = :id"
                )

                with self.db_engine.connect() as conn:
                    conn.execute(text(update_sql), params)
                    conn.commit()

        # Retry loop
        retries = 4
        backoff = 0.1
        for attempt in range(retries):
            try:
                _inner_update()
                return
            except sqlite3.OperationalError as oe:
                # Database locked - wait and retry
                self.logger.warning(
                    f"sqlite OperationalError on update_job_record (attempt {attempt+1}/{retries}): {oe}"
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            except Exception as e:
                self.logger.error(f"Failed to update job record: {e}")
                return

    def record_site_failure(
        self,
        operation_id: str,
        site_url: str,
        error: Exception,
        site_name: Optional[str] = None,
        discovery_method: Optional[str] = None,
        http_status: Optional[int] = None,
        response_time_ms: Optional[float] = None,
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
        self, error: Exception, http_status: Optional[int] = None
    ) -> FailureType:
        """Categorize the type of failure based on error and context."""
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        # Network-related errors
        if any(
            keyword in error_str
            for keyword in ["connection", "network", "dns", "hostname", "resolve"]
        ):
            return FailureType.NETWORK_ERROR

        # SSL/TLS errors
        if any(
            keyword in error_str
            for keyword in ["ssl", "tls", "certificate", "handshake"]
        ):
            return FailureType.SSL_ERROR

        # Timeout errors
        if any(
            keyword in error_str for keyword in ["timeout", "timed out", "read timeout"]
        ):
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
        if (
            any(
                keyword in error_str
                for keyword in ["rate limit", "too many requests", "429"]
            )
            or http_status == 429
        ):
            return FailureType.RATE_LIMITED

        # Authentication errors
        if any(
            keyword in error_str
            for keyword in ["unauthorized", "forbidden", "authentication", "401", "403"]
        ) or http_status in [401, 403]:
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

    def get_site_failures(self, operation_id: str) -> List[SiteFailure]:
        """Get all site failures for an operation."""
        with self._lock:
            if operation_id in self.active_operations:
                metrics = self.active_operations[operation_id].get("metrics")
                if metrics and metrics.site_failures:
                    return metrics.site_failures[:]
        return []

    def get_failure_summary(self, operation_id: str) -> Dict[str, Any]:
        """Get a summary of failures for an operation."""
        failures = self.get_site_failures(operation_id)

        if not failures:
            return {"total_failures": 0, "failure_types": {}, "failed_sites": []}

        # Count failures by type
        failure_counts = {}
        for failure in failures:
            failure_type = failure.failure_type.value
            failure_counts[failure_type] = failure_counts.get(failure_type, 0) + 1

        # Get failed site URLs
        failed_sites = [failure.site_url for failure in failures]

        # Calculate retry statistics
        total_retries = sum(failure.retry_count for failure in failures)
        avg_retries = total_retries / len(failures) if failures else 0

        return {
            "total_failures": len(failures),
            "failure_types": failure_counts,
            "failed_sites": failed_sites,
            "total_retries": total_retries,
            "average_retries": avg_retries,
            "most_common_failure": (
                max(failure_counts.items(), key=lambda x: x[1])[0]
                if failure_counts
                else None
            ),
        }

    def identify_common_failures(self, operation_id: str) -> List[Dict[str, Any]]:
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
                pattern["avg_response_time"] = (
                    current_avg * (pattern["count"] - 1) + failure.response_time_ms
                ) / pattern["count"]

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
                report.append(
                    f"{i}. {pattern['failure_type']} ({pattern['count']} sites)"
                )
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
        error_message: Optional[str] = None,
        content_length: Optional[int] = None,
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
        status_codes: List[int],
        notes: Optional[str] = None,
    ):
        """Update the effectiveness tracking for a discovery method."""
        effectiveness = self._get_or_create_method_effectiveness(
            source_id, source_url, discovery_method
        )

        # Update statistics
        effectiveness.attempt_count += 1
        effectiveness.last_attempt = datetime.now(timezone.utc)
        effectiveness.status = status
        effectiveness.articles_found = max(effectiveness.articles_found, articles_found)

        # Calculate rolling average response time
        total_time = (
            effectiveness.avg_response_time_ms * (effectiveness.attempt_count - 1)
            + response_time_ms
        )
        effectiveness.avg_response_time_ms = total_time / effectiveness.attempt_count

        # Update success rate
        if status == DiscoveryMethodStatus.SUCCESS and articles_found > 0:
            success_count = max(
                1, effectiveness.attempt_count * effectiveness.success_rate / 100
            )
            effectiveness.success_rate = (
                success_count / effectiveness.attempt_count
            ) * 100
        else:
            # Decay success rate if this attempt failed
            effectiveness.success_rate = (
                effectiveness.success_rate
                * (effectiveness.attempt_count - 1)
                / effectiveness.attempt_count
            )

        # Update recent status codes (keep last 10)
        effectiveness.last_status_codes.extend(status_codes)
        effectiveness.last_status_codes = effectiveness.last_status_codes[-10:]

        if notes:
            effectiveness.notes = notes

        # Store in database
        self._store_method_effectiveness(effectiveness)

    def get_effective_discovery_methods(self, source_id: str) -> List[DiscoveryMethod]:
        """Get list of discovery methods that work well for a source."""
        try:
            with self.db_engine.connect() as connection:
                result = connection.execute(
                    text(
                        """
                        SELECT discovery_method, success_rate, articles_found,
                               attempt_count, status
                        FROM discovery_method_effectiveness 
                        WHERE source_id = :source_id 
                        ORDER BY success_rate DESC, articles_found DESC
                    """
                    ),
                    {"source_id": source_id},
                )

                effective_methods = []
                for row in result:
                    # Consider effective if success rate > 50% and found articles
                    if (
                        row.success_rate > 50
                        and row.articles_found > 0
                        and row.attempt_count >= 2
                    ):
                        try:
                            method = DiscoveryMethod(row.discovery_method)
                            effective_methods.append(method)
                        except ValueError:
                            continue  # Skip unknown methods

                return effective_methods

        except Exception as e:
            self.logger.error(f"Failed to get effective methods: {e}")
            # Return all methods as fallback
            return [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
                DiscoveryMethod.STORYSNIFFER,
            ]

    def _store_http_status_tracking(self, tracking: HTTPStatusTracking):
        """Store HTTP status tracking in database."""

        def _do_insert():
            with self.db_engine.connect() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO http_status_tracking 
                        (source_id, source_url, discovery_method, attempted_url,
                         status_code, status_category, response_time_ms, 
                         timestamp, operation_id, error_message, content_length)
                        VALUES (:source_id, :source_url, :discovery_method, 
                               :attempted_url, :status_code, :status_category,
                               :response_time_ms, :timestamp, :operation_id,
                               :error_message, :content_length)
                    """
                    ),
                    asdict(tracking),
                )
                connection.commit()

        retries = 3
        backoff = 0.1
        for attempt in range(retries):
            try:
                _do_insert()
                return
            except sqlite3.OperationalError as oe:
                # Use logger args to avoid long f-strings
                self.logger.warning(
                    "sqlite OperationalError on http_status insert (%d/%d): %s",
                    attempt + 1,
                    retries,
                    oe,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            except Exception as e:
                self.logger.error("Failed to store HTTP status tracking: %s", e)
                return

    def _get_or_create_method_effectiveness(
        self,
        source_id: str,
        source_url: str,
        discovery_method: DiscoveryMethod,
    ) -> DiscoveryMethodEffectiveness:
        """Get existing or create new method effectiveness record."""
        try:
            with self.db_engine.connect() as connection:
                result = connection.execute(
                    text(
                        """
                        SELECT * FROM discovery_method_effectiveness
                        WHERE source_id = :source_id
                        AND discovery_method = :discovery_method
                    """
                    ),
                    {
                        "source_id": source_id,
                        "discovery_method": discovery_method.value,
                    },
                )

                row = result.fetchone()
                if row:
                    return DiscoveryMethodEffectiveness(
                        source_id=row.source_id,
                        source_url=row.source_url,
                        discovery_method=DiscoveryMethod(row.discovery_method),
                        status=DiscoveryMethodStatus(row.status),
                        articles_found=row.articles_found,
                        success_rate=row.success_rate,
                        last_attempt=row.last_attempt,
                        attempt_count=row.attempt_count,
                        avg_response_time_ms=row.avg_response_time_ms,
                        last_status_codes=json.loads(row.last_status_codes or "[]"),
                        notes=row.notes,
                    )
        except Exception as e:
            self.logger.error(f"Failed to get method effectiveness: {e}")

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

    def _store_method_effectiveness(self, effectiveness: DiscoveryMethodEffectiveness):
        """Store or update method effectiveness in database."""

        def _do_upsert():
            with self.db_engine.connect() as connection:
                # Try to update existing record
                result = connection.execute(
                    text(
                        """
                        UPDATE discovery_method_effectiveness
                        SET status = :status, articles_found = :articles_found,
                            success_rate = :success_rate,
                            last_attempt = :last_attempt,
                            attempt_count = :attempt_count,
                            avg_response_time_ms = :avg_response_time_ms,
                            last_status_codes = :last_status_codes,
                            notes = :notes
                        WHERE source_id = :source_id
                        AND discovery_method = :discovery_method
                    """
                    ),
                    {
                        "source_id": effectiveness.source_id,
                        "discovery_method": (effectiveness.discovery_method.value),
                        "status": effectiveness.status.value,
                        "articles_found": effectiveness.articles_found,
                        "success_rate": effectiveness.success_rate,
                        "last_attempt": effectiveness.last_attempt,
                        "attempt_count": effectiveness.attempt_count,
                        "avg_response_time_ms": (effectiveness.avg_response_time_ms),
                        "last_status_codes": json.dumps(
                            effectiveness.last_status_codes
                        ),
                        "notes": effectiveness.notes,
                    },
                )

                if result.rowcount == 0:
                    # Insert new record
                    connection.execute(
                        text(
                            """
                            INSERT INTO discovery_method_effectiveness
                            (source_id, source_url, discovery_method, status,
                             articles_found, success_rate, last_attempt,
                             attempt_count, avg_response_time_ms,
                             last_status_codes, notes)
                            VALUES (:source_id, :source_url, :discovery_method,
                                   :status, :articles_found, :success_rate,
                                   :last_attempt, :attempt_count,
                                   :avg_response_time_ms, :last_status_codes,
                                   :notes)
                        """
                        ),
                        {
                            "source_id": effectiveness.source_id,
                            "source_url": effectiveness.source_url,
                            "discovery_method": (effectiveness.discovery_method.value),
                            "status": effectiveness.status.value,
                            "articles_found": effectiveness.articles_found,
                            "success_rate": effectiveness.success_rate,
                            "last_attempt": effectiveness.last_attempt,
                            "attempt_count": effectiveness.attempt_count,
                            "avg_response_time_ms": (
                                effectiveness.avg_response_time_ms
                            ),
                            "last_status_codes": json.dumps(
                                effectiveness.last_status_codes
                            ),
                            "notes": effectiveness.notes,
                        },
                    )

                connection.commit()

        retries = 3
        backoff = 0.1
        for attempt in range(retries):
            try:
                _do_upsert()
                return
            except sqlite3.OperationalError as oe:
                # Shorten the logged message and avoid long f-strings
                self.logger.warning(
                    "sqlite OperationalError on method upsert (%d/%d): %s",
                    attempt + 1,
                    retries,
                    oe,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            except Exception as e:
                self.logger.error(f"Failed to store method effectiveness: {e}")
                return

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

    def update_progress(self, processed: int, total: int, message: str = ""):
        """Update operation progress."""
        current_time = time.time()
        elapsed = current_time - self.start_time

        # Calculate metrics
        success_rate = (processed / total * 100) if total > 0 else 0
        items_per_second = processed / elapsed if elapsed > 0 else 0

        # Estimate completion time
        estimated_completion = None
        if items_per_second > 0 and total > processed:
            remaining_items = total - processed
            remaining_seconds = remaining_items / items_per_second
            estimated_completion = (
                datetime.now(timezone.utc).timestamp() + remaining_seconds
            )
            estimated_completion = datetime.fromtimestamp(
                estimated_completion, timezone.utc
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
            self.tracker.logger.info(f"Operation {self.operation_id}: {message}")

    def log_message(self, message: str, level: str = "info"):
        """Log a message for this operation."""
        logger = self.tracker.logger
        getattr(logger, level)(f"Operation {self.operation_id}: {message}")


def create_telemetry_system(
    db_engine, api_base_url: Optional[str] = None, api_key: Optional[str] = None
) -> OperationTracker:
    """Factory function to create telemetry system."""
    reporter = None
    if api_base_url:
        reporter = TelemetryReporter(api_base_url, api_key)

    return OperationTracker(db_engine, reporter)
