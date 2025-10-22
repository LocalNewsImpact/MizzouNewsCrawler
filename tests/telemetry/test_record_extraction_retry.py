from __future__ import annotations

from datetime import datetime
from typing import Any

from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics,
)

from sqlalchemy.exc import IntegrityError


class _FakeConn:
    def __init__(self, fail_once: bool = True):
        self._fail_once = fail_once
        self.executed = []

    def execute(self, sql, params=None):
        # Simulate first call raising IntegrityError
        if self._fail_once:
            self._fail_once = False
            # Provide a real exception instance as 'orig' to satisfy typing
            raise IntegrityError("duplicate key", params, Exception("orig"))
        # Record that we executed SQL
        self.executed.append((sql, params))

    def cursor(self):
        return self

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _FakeStore:
    def __init__(self, conn: _FakeConn, is_postgres: bool = True):
        self._conn = conn
        self._is_postgres = is_postgres

    def submit(self, task: Any, *, ensure=None) -> None:
        # Execute task synchronously with our fake conn
        task(self._conn)


def test_record_extraction_resync_and_retry(tmp_path, caplog):
    caplog.set_level("DEBUG")

    # Build metrics
    metrics = ExtractionMetrics(
        operation_id="op1",
        article_id="a1",
        url="https://example.com/article",
        publisher="Example",
    )
    metrics.start_time = datetime.utcnow()
    metrics.end_time = datetime.utcnow()
    metrics.total_duration_ms = 123.4
    metrics.methods_attempted = ["method_a"]
    metrics.method_timings = {"method_a": 10}
    metrics.method_success = {"method_a": True}
    metrics.successful_method = "method_a"

    conn = _FakeConn(fail_once=True)
    store = _FakeStore(conn, is_postgres=True)

    # Construct telemetry with no store then inject our fake store to avoid
    # strict type checks on the constructor parameter in tests.
    telemetry = ComprehensiveExtractionTelemetry(store=None)
    telemetry._store = store  # type: ignore[attr-defined]

    # Should not raise despite initial IntegrityError; second attempt succeeds
    telemetry.record_extraction(metrics)

    # Verify that after retry we executed at least one INSERT
    assert any(
        "INSERT INTO extraction_telemetry_v2" in (
            sql if isinstance(sql, str) else str(sql)
        )
        for sql, _ in conn.executed
    )

    # Ensure we executed a sequence resync SQL statement on the connection
    assert any(
        (isinstance(sql, str) and ("pg_get_serial_sequence" in sql or "setval" in sql))
        for sql, _ in conn.executed
    ), "Expected sequence resync SQL to be executed on the connection"
