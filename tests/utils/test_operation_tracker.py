import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

import pytest
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from src.telemetry.store import TelemetryStore
from src.utils.discovery_outcomes import DiscoveryOutcome, DiscoveryResult
from src.utils.telemetry import (
    DiscoveryMethod,
    FailureType,
    DiscoveryMethodStatus,
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
        # TelemetryStore expects a proper SQLite URL, not a raw path
        db_url = f"sqlite:///{db_path}"
        store = TelemetryStore(database=db_url, async_writes=False)
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
                raise SQLAlchemyOperationalError("simulated lock", None, None)
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
            ("SELECT status, metrics, result_summary FROM operations WHERE id = ?"),
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
            "SELECT status_code, status_category, timestamp FROM http_status_tracking"
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


def test_record_discovery_outcome_persists_row(tracker_factory):
    tracker, store, db_path = tracker_factory("discovery_outcome.db")

    result = DiscoveryResult(
        DiscoveryOutcome.NEW_ARTICLES_FOUND,
        articles_found=4,
        articles_new=3,
        articles_duplicate=1,
        method_used="rss",
        metadata={"methods_attempted": ["rss", "newspaper"]},
    )

    tracker.record_discovery_outcome(
        operation_id="op-1",
        source_id="src-1",
        source_name="Source One",
        source_url="https://example.com",
        discovery_result=result,
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT outcome, articles_found, articles_new, methods_attempted, method_used, metadata "
            "FROM discovery_outcomes"
        ).fetchone()

    assert row["outcome"] == DiscoveryOutcome.NEW_ARTICLES_FOUND.value
    assert row["articles_found"] == 4
    assert row["articles_new"] == 3
    assert row["methods_attempted"] == "rss,newspaper"
    assert row["method_used"] == "rss"
    metadata = json.loads(row["metadata"])
    assert metadata["methods_attempted"] == ["rss", "newspaper"]

    store.shutdown()


def test_get_discovery_outcomes_report_returns_expected_summary(tracker_factory):
    tracker, store, _ = tracker_factory("discovery_report.db")

    success = DiscoveryResult(
        DiscoveryOutcome.NEW_ARTICLES_FOUND,
        articles_found=2,
        articles_new=2,
        metadata={"methods_attempted": ["rss"]},
    )
    failure = DiscoveryResult(
        DiscoveryOutcome.TIMEOUT,
        articles_found=0,
        metadata={"methods_attempted": ["rss"]},
    )

    tracker.record_discovery_outcome(
        "op-good", "src-good", "Good Source", "https://good.example", success
    )
    tracker.record_discovery_outcome(
        "op-bad", "src-bad", "Bad Source", "https://bad.example", failure
    )

    report = tracker.get_discovery_outcomes_report(hours_back=48)

    summary = report["summary"]
    assert summary["total_sources"] == 2
    assert summary["technical_success_rate"] == 50.0
    assert summary["content_success_rate"] == 50.0

    breakdown_outcomes = {item["outcome"] for item in report["outcome_breakdown"]}
    assert DiscoveryOutcome.NEW_ARTICLES_FOUND.value in breakdown_outcomes
    assert DiscoveryOutcome.TIMEOUT.value in breakdown_outcomes

    top_sources = report["top_performing_sources"]
    assert top_sources[0]["source_name"] == "Good Source"
    assert top_sources[0]["content_success_rate"] == 100.0

    store.shutdown()


def test_record_verification_batch_persists_payload(tracker_factory):
    tracker, store, db_path = tracker_factory("verification_batch.db")

    tracker.record_verification_batch(
        job_name="verify-1",
        batch_size=50,
        verified_articles=20,
        verified_non_articles=25,
        verification_errors=5,
        total_processed=45,
        batch_time_seconds=30.5,
        avg_verification_time_ms=675.2,
        total_time_ms=2056.0,
        sources_processed=["Source A", "Source B"],
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT job_name, batch_size, verified_articles, total_processed, sources_processed, timestamp "
            "FROM verification_telemetry"
        ).fetchone()

    assert row["job_name"] == "verify-1"
    assert row["batch_size"] == 50
    assert row["verified_articles"] == 20
    assert row["total_processed"] == 45
    assert json.loads(row["sources_processed"]) == ["Source A", "Source B"]
    parsed = datetime.fromisoformat(row["timestamp"].replace(" ", "T"))
    assert isinstance(parsed, datetime)

    store.shutdown()


def test_track_http_status_logs_warning_for_errors(tracker_factory, caplog):
    tracker, store, db_path = tracker_factory("http_status_logging.db")
    op_id = "op-http2"
    tracker.start_operation(op_id, OperationType.CRAWL_DISCOVERY)

    with caplog.at_level("WARNING"):
        tracker.track_http_status(
            operation_id=op_id,
            source_id="src-err",
            source_url="https://err.example",
            discovery_method=DiscoveryMethod.RSS_FEED,
            attempted_url="https://err.example/feed",
            status_code=500,
            response_time_ms=321.0,
            error_message="Server error",
            content_length=None,
        )

    assert any("HTTP 500" in rec.getMessage() for rec in caplog.records)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status_code, status_category, error_message FROM http_status_tracking"
        ).fetchone()

    assert row["status_code"] == 500
    assert row["status_category"] == "5xx"
    assert row["error_message"] == "Server error"

    store.shutdown()


def test_discovery_method_effectiveness_updates_and_fetches(tracker_factory):
    tracker, store, db_path = tracker_factory("method_effectiveness.db")
    source_id = "src-method"
    tracker.update_discovery_method_effectiveness(
        source_id=source_id,
        source_url="https://method.example",
        discovery_method=DiscoveryMethod.RSS_FEED,
        status=DiscoveryMethodStatus.SUCCESS,
        articles_found=3,
        response_time_ms=120.0,
        status_codes=[200, 200],
        notes="Initial success",
    )

    tracker.update_discovery_method_effectiveness(
        source_id=source_id,
        source_url="https://method.example",
        discovery_method=DiscoveryMethod.RSS_FEED,
        status=DiscoveryMethodStatus.SERVER_ERROR,
        articles_found=0,
        response_time_ms=300.0,
        status_codes=[503],
        notes="Second attempt",
    )

    tracker.update_discovery_method_effectiveness(
        source_id=source_id,
        source_url="https://method.example",
        discovery_method=DiscoveryMethod.RSS_FEED,
        status=DiscoveryMethodStatus.SUCCESS,
        articles_found=5,
        response_time_ms=110.0,
        status_codes=[200],
        notes="Recovered",
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT articles_found, attempt_count, success_rate, avg_response_time_ms, last_status_codes, notes "
            "FROM discovery_method_effectiveness"
        ).fetchone()

    assert row["articles_found"] == 5
    assert row["attempt_count"] == 3
    assert row["notes"] == "Recovered"
    assert abs(float(row["avg_response_time_ms"]) - (530.0 / 3.0)) < 0.1
    assert json.loads(row["last_status_codes"]) == [200, 200, 503, 200]

    effective = tracker.get_effective_discovery_methods(source_id)
    assert DiscoveryMethod.RSS_FEED in effective
    assert tracker.has_historical_data(source_id) is True
    assert tracker.has_historical_data("unknown-source") is False

    store.shutdown()


def test_get_or_create_method_effectiveness_handles_corrupt_rows(tracker_factory):
    tracker, store, db_path = tracker_factory("method_effectiveness_corrupt.db")
    source_id = "src-corrupt"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO discovery_method_effectiveness (
                source_id, source_url, discovery_method, status,
                articles_found, success_rate, last_attempt, attempt_count,
                avg_response_time_ms, last_status_codes, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                "https://corrupt.example",
                DiscoveryMethod.RSS_FEED.value,
                DiscoveryMethodStatus.SUCCESS.value,
                "3",  # string to force conversion
                "75.5",
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "2",
                "150.0",
                "not-a-json",
                None,
            ),
        )
        conn.commit()

    effectiveness = tracker._get_or_create_method_effectiveness(
        source_id,
        "https://corrupt.example",
        DiscoveryMethod.RSS_FEED,
    )

    assert effectiveness.articles_found == 3
    assert effectiveness.attempt_count == 2
    assert effectiveness.success_rate == pytest.approx(75.5)
    assert effectiveness.last_status_codes == []

    store.shutdown()


def test_failure_summary_and_report_handles_multiple_types(tracker_factory, caplog):
    tracker, store, _ = tracker_factory("failure_summary.db")
    op_id = "op-failure"
    tracker.start_operation(op_id, OperationType.CRAWL_DISCOVERY)

    with caplog.at_level("INFO"):
        tracker.record_site_failure(
            operation_id=op_id,
            site_url="https://content-empty.example",
            error=Exception("No articles were discovered"),
            site_name="Content Empty",
            discovery_method="all_methods",
            http_status=200,
            response_time_ms=10.0,
            retry_count=1,
        )

    tracker.record_site_failure(
        operation_id=op_id,
        site_url="https://ssl.example",
        error=Exception("SSL handshake failed"),
        site_name="SSL Site",
        discovery_method="rss",
        http_status=503,
        response_time_ms=250.0,
        retry_count=2,
    )

    tracker.record_site_failure(
        operation_id=op_id,
        site_url="https://timeout.example",
        error=Exception("Read timeout"),
        site_name="Timeout Site",
        discovery_method="rss",
        http_status=504,
        response_time_ms=400.0,
        retry_count=0,
    )

    summary = tracker.get_failure_summary(op_id)
    assert summary["total_failures"] == 3
    assert summary["failure_types"][FailureType.SSL_ERROR.value] == 1
    assert summary["failure_types"][FailureType.TIMEOUT.value] == 1
    assert summary["failure_types"][FailureType.CONTENT_ERROR.value] == 1
    assert summary["total_retries"] == 3
    assert summary["average_retries"] == pytest.approx(1.0)
    assert summary["most_common_failure"] in {
        FailureType.SSL_ERROR.value,
        FailureType.TIMEOUT.value,
        FailureType.CONTENT_ERROR.value,
    }

    breakdown = tracker.identify_common_failures(op_id)
    assert len(breakdown) == 3
    ssl_pattern = next(item for item in breakdown if item["failure_type"] == FailureType.SSL_ERROR.value)
    assert ssl_pattern["avg_response_time"] == pytest.approx(250.0)
    assert 503 in ssl_pattern["http_statuses"]

    with caplog.at_level("INFO"):
        report = tracker.generate_failure_report(op_id)
    assert "Failure Breakdown by Type" in report
    assert "SSL Site" not in report  # ensure only aggregated info is reported

    info_logs = [rec for rec in caplog.records if rec.levelname == "INFO"]
    assert any("content-empty" in rec.getMessage().lower() for rec in info_logs)

    store.shutdown()
