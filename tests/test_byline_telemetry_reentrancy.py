import pytest

from src.utils.byline_telemetry import BylineCleaningTelemetry


class DummyConn:
    def __init__(self):
        self.exec_calls = []

    def execute(self, sql):
        # record that execute was called; store SQL for inspection
        self.exec_calls.append(str(sql))

    def commit(self):
        pass


class MockConnectionCtx:
    def __init__(self, telemetry, conn):
        self.telemetry = telemetry
        self.conn = conn

    def __enter__(self):
        # Simulate re-entrant call into _ensure_tables while a connection is being opened
        # This should be handled by the re-entrancy guard and not cause recursion
        self.telemetry._ensure_tables()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class MockStore:
    def __init__(self, telemetry):
        self.telemetry = telemetry
        self.conn = DummyConn()

    def connection(self):
        return MockConnectionCtx(self.telemetry, self.conn)


def test_ensure_tables_is_non_reentrant():
    telemetry = BylineCleaningTelemetry(enable_telemetry=True, store=None)

    # Inject our mock store which will re-enter _ensure_tables when a connection is obtained
    mock_store = MockStore(telemetry)
    telemetry._store = mock_store

    # Calling _ensure_tables should complete without raising (no RecursionError)
    telemetry._ensure_tables()

    # The re-entrancy guard should be cleared after the call
    assert getattr(telemetry, "_ensuring_tables", False) is False

    # The mock connection's execute should have been called to create tables
    assert mock_store.conn.exec_calls, "Expected SQL execution to be attempted"
