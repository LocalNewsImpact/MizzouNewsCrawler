"""Tests for the telemetry store helpers."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from src.telemetry.store import TelemetryStore, _resolve_sqlite_path, get_store


@pytest.fixture
def temp_db_uri(tmp_path):
    """Create a sqlite URI pointing at a temporary file."""
    db_path = tmp_path / "telemetry_store.db"
    return f"sqlite:///{db_path}"  # pragma: no cover - trivial path helper


def _fetch_all(uri: str, query: str) -> list[tuple[object, ...]]:
    """Helper to read rows from the sqlite file for assertions."""
    path = Path(uri.replace("sqlite:///", "", 1))
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(query)
        rows = cursor.fetchall()
    return rows


class TestSyncTelemetryStore:
    def test_submit_executes_task_and_creates_schema(self, temp_db_uri):
        store = TelemetryStore(database=temp_db_uri, async_writes=False)

        def _task(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO events(value) VALUES (?)", ("hello",))

        ddl = "CREATE TABLE IF NOT EXISTS events (value TEXT)"
        store.submit(_task, ensure=[ddl])

        rows = _fetch_all(temp_db_uri, "SELECT value FROM events")
        assert rows == [("hello",)]
        assert ddl in store._ddl_cache  # noqa: SLF001

    def test_submit_raises_errors_immediately(self, temp_db_uri):
        store = TelemetryStore(database=temp_db_uri, async_writes=False)

        def _task(_: sqlite3.Connection) -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            store.submit(_task)

    def test_connection_context_closes_connection(self, temp_db_uri):
        store = TelemetryStore(database=temp_db_uri, async_writes=False)

        with store.connection() as conn:
            conn.execute("SELECT 1")

        # After context exit, connection should be closed
        # (SQLAlchemy raises ResourceClosedError instead of ProgrammingError)
        with pytest.raises((sqlite3.ProgrammingError, Exception)):
            conn.execute("SELECT 1")

    def test_shutdown_noop_for_sync_store(self, temp_db_uri):
        store = TelemetryStore(database=temp_db_uri, async_writes=False)
        store.shutdown(wait=True)  # should not raise even though no worker


class TestAsyncTelemetryStore:
    def test_async_submit_flush_and_shutdown(self, temp_db_uri):
        store = TelemetryStore(database=temp_db_uri, async_writes=True)
        status = []
        done = threading.Event()

        def _task(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO metrics(event) VALUES (?)", ("ok",))
            status.append("ran")
            done.set()

        ddl = "CREATE TABLE IF NOT EXISTS metrics (event TEXT)"
        store.submit(_task, ensure=[ddl])

        store.flush()
        assert done.wait(timeout=2)
        assert status == ["ran"]

        rows = _fetch_all(temp_db_uri, "SELECT event FROM metrics")
        assert rows == [("ok",)]

        store.shutdown(wait=True)
        store.shutdown(wait=True)  # idempotent stop


class TestHelpers:
    @pytest.mark.parametrize(
        "database, expected",
        [
            ("sqlite:///tmp/test.db", "tmp/test.db"),
            ("sqlite:///:memory:", ":memory:"),
            ("/absolute/path.db", "/absolute/path.db"),
        ],
    )
    def test_resolve_sqlite_path(self, database: str, expected: str) -> None:
        assert _resolve_sqlite_path(database) == expected

    def test_get_store_returns_singleton(self, monkeypatch) -> None:
        from src.telemetry import store as store_module

        monkeypatch.setattr(store_module, "_default_store", None)

        shared = get_store(database="sqlite:///:memory:")
        again = get_store()

        try:
            assert shared is again
        finally:
            shared.shutdown(wait=True)
            monkeypatch.setattr(store_module, "_default_store", None)
