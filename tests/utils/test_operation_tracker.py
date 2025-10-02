import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

import pytest

from src.telemetry.store import TelemetryStore
from src.utils.telemetry import (
    DiscoveryMethod,
    FailureType,
    OperationMetrics,
    OperationStatus,
    OperationTracker,
    OperationType,
    _format_timestamp,
)


@pytest.fixture
def tracker_factory(tmp_path):
    def _factory(name: str) -> tuple[OperationTracker, TelemetryStore, str]:
        db_path = tmp_path / name
        store = TelemetryStore(database=str(db_path), async_writes=False)
        tracker = OperationTracker(store=store)
        return tracker, store, str(db_path)

    return _factory


def test_categorize_failure_type_handles_edge_cases(tracker_factory):
    tracker, store, _ = tracker_factory("categorize.db")

    cases = [
        (
            Exception("Network connection dropped"),
            None,
            FailureType.NETWORK_ERROR,
        ),
        (Exception("SSL certificate error"), None, FailureType.SSL_ERROR),
        (Exception("Read timeout"), None, FailureType.TIMEOUT),
        (
            Exception("Cloudflare 503 service temporarily unavailable"),
            None,
            FailureType.CLOUDFLARE_PROTECTION,
        ),
        (Exception("RSS feed parsing failure"), None, FailureType.RSS_ERROR),
        (Exception("content empty"), None, FailureType.CONTENT_ERROR),
        (
            Exception("Authentication forbidden"),
            403,
            FailureType.AUTHENTICATION_ERROR,
        ),
        (Exception("Rate limit exceeded"), 429, FailureType.RATE_LIMITED),
        (Exception("Upstream returned 502"), 502, FailureType.HTTP_ERROR),
        (Exception("No matching keywords"), None, FailureType.UNKNOWN),
    ]

    for error, status, expected in cases:
        assert tracker.categorize_failure_type(error, status) is expected

    store.shutdown()


def test_operation_lifecycle_handles_retry(tracker_factory, monkeypatch):
    tracker, store, db_path = tracker_factory("lifecycle.db")

    fail_flag = {"remaining": 1}
    executed_statements: list[str] = []

    class RetryCursor:
        def __init__(self, cursor: sqlite3.Cursor):
            self._cursor = cursor

        def execute(self, sql: str, params: tuple | dict | None = None):
            executed_statements.append(sql.strip().split()[0].upper())
            if "INSERT INTO operations" in sql and fail_flag["remaining"]:
                fail_flag["remaining"] -= 1
                raise sqlite3.OperationalError("simulated lock")
            if params is None:
                return self._cursor.execute(sql)
            return self._cursor.execute(sql, params)

        def fetchone(self):
            return self._cursor.fetchone()

        def close(self):
            self._cursor.close()

    class RetryConnection:
        def __init__(self, connection: sqlite3.Connection):
            self._connection = connection

        def cursor(self):
            return RetryCursor(self._connection.cursor())

        def rollback(self):
            self._connection.rollback()

        def commit(self):
            self._connection.commit()

        def close(self):
            self._connection.close()

    def run_with_retry(task: Callable[[Any], None], *, ensure=None):
        conn = sqlite3.connect(db_path)
        try:
            if ensure:
                for ddl in ensure:
                    conn.execute(ddl)
                conn.commit()
            retry_conn = RetryConnection(conn)
            task(retry_conn)
            conn.commit()
        finally:
            conn.close()

    monkeypatch.setattr(tracker._store, "submit", run_with_retry)

    operation_id = "op-lifecycle"
    tracker.start_operation(
        operation_id,
        OperationType.CRAWL_DISCOVERY,
        user_id="u1",
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        assert row["status"] == OperationStatus.STARTED.value

    metrics = OperationMetrics(
        total_items=10,
        processed_items=5,
        failed_items=1,
    )
    tracker.update_progress(operation_id, metrics)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, metrics FROM operations WHERE id = ?",
            (operation_id,),
        ).fetchone()
        assert row["status"] == OperationStatus.IN_PROGRESS.value
        stored_metrics = json.loads(row["metrics"])
        assert stored_metrics["processed_items"] == 5
        assert stored_metrics["total_items"] == 10

    summary = {"completed": True}
    tracker.complete_operation(operation_id, result_summary=summary)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            ("SELECT status, metrics, result_summary " "FROM operations WHERE id = ?"),
            (operation_id,),
        ).fetchone()
        assert row["status"] == OperationStatus.COMPLETED.value
        stored_metrics = json.loads(row["metrics"])
        assert stored_metrics["failed_items"] == 1
        stored_summary = json.loads(row["result_summary"])
        assert stored_summary == summary

    assert executed_statements.count("INSERT") >= 2
    store.shutdown()


def test_record_site_failure_updates_metrics(tracker_factory):
    tracker, store, _ = tracker_factory("site_failure.db")
    operation_id = "op-site"
    tracker.start_operation(operation_id, OperationType.CRAWL_DISCOVERY)

    tracker.record_site_failure(
        operation_id=operation_id,
        site_url="https://example.com",
        error=Exception("SSL handshake failed"),
        site_name="Example",
        discovery_method=DiscoveryMethod.RSS_FEED.value,
        http_status=503,
        response_time_ms=250.0,
        retry_count=2,
    )

    metrics = tracker.active_operations[operation_id]["metrics"]
    assert metrics.failed_sites == 1
    assert metrics.failed_items == 1
    assert metrics.site_failures is not None
    assert len(metrics.site_failures) == 1

    failure = metrics.site_failures[0]
    assert failure.failure_type is FailureType.SSL_ERROR
    assert failure.http_status == 503
    assert failure.retry_count == 2
    assert failure.response_time_ms == 250.0
    assert failure.site_url == "https://example.com"

    store.shutdown()


def test_track_http_status_uses_normalized_timestamps(tracker_factory):
    tracker, store, db_path = tracker_factory("http_status.db")
    operation_id = "op-http"
    tracker.start_operation(operation_id, OperationType.CRAWL_DISCOVERY)

    tracker.track_http_status(
        operation_id=operation_id,
        source_id="src-1",
        source_url="https://example.com",
        discovery_method=DiscoveryMethod.RSS_FEED,
        attempted_url="https://example.com/feed",
        status_code=404,
        response_time_ms=123.4,
        error_message="Not found",
        content_length=0,
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status_code, status_category, timestamp "
            "FROM http_status_tracking"
        ).fetchone()

    assert row["status_code"] == 404
    assert row["status_category"] == "4xx"

    parsed_timestamp = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
    normalized = _format_timestamp(datetime.now(timezone.utc))
    assert "T" not in row["timestamp"]
    assert row["timestamp"].count(":") == 2
    assert isinstance(parsed_timestamp, datetime)
    assert row["timestamp"] <= normalized

    store.shutdown()
