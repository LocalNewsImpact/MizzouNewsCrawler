"""Tests for TelemetryStore with PostgreSQL.

NOTE: TelemetryStore is now PostgreSQL-only. SQLite support has been removed
to prevent production failures caused by silent fallback to SQLite behavior.
"""

from __future__ import annotations

import os
import threading

import pytest

from src.telemetry.store import TelemetryStore

# Check if we have PostgreSQL connection info for testing
POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL


@pytest.fixture
def postgres_db_uri():
    """Get PostgreSQL test database URI."""
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured")
    return POSTGRES_TEST_URL


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestPostgreSQLCompatibility:
    """Test that PostgreSQL works with the SQLAlchemy implementation."""

    def test_postgres_connection(self, postgres_db_uri):
        """Test that we can connect to PostgreSQL."""
        store = TelemetryStore(database=postgres_db_uri, async_writes=False)

        with store.connection() as conn:
            result = conn.execute("SELECT 1")
            if hasattr(result, "fetchall"):
                rows = result.fetchall()
            else:
                rows = list(result)
            assert len(rows) == 1

    def test_postgres_table_creation(self, postgres_db_uri):
        """Test creating tables in PostgreSQL."""
        store = TelemetryStore(database=postgres_db_uri, async_writes=False)

        # Use a unique table name to avoid conflicts
        import uuid

        table_name = f"test_telemetry_{uuid.uuid4().hex[:8]}"

        ddl = (
            f"CREATE TABLE IF NOT EXISTS {table_name} "
            f"(id SERIAL PRIMARY KEY, value TEXT)"
        )

        def _task(conn):
            conn.execute(
                f"INSERT INTO {table_name}(value) VALUES (?)", ("postgres_test",)
            )

        try:
            store.submit(_task, ensure=[ddl])

            # Verify the insert
            with store.connection() as conn:
                result = conn.execute(f"SELECT value FROM {table_name}")
                if hasattr(result, "fetchall"):
                    rows = result.fetchall()
                else:
                    rows = list(result)
                assert len(rows) == 1
                # Access by column name (rows are dict-like after _mapping conversion)
                assert rows[0]["value"] == "postgres_test"
        finally:
            # Clean up
            try:
                with store.connection() as conn:
                    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                    conn.commit()
            except Exception:
                pass

    def test_postgres_async_writes(self, postgres_db_uri):
        """Test async writes to PostgreSQL."""
        import uuid

        table_name = f"test_async_{uuid.uuid4().hex[:8]}"

        store = TelemetryStore(database=postgres_db_uri, async_writes=True)

        ddl = f"CREATE TABLE IF NOT EXISTS {table_name} (event TEXT)"
        done = threading.Event()

        def _task(conn):
            conn.execute(f"INSERT INTO {table_name}(event) VALUES (?)", ("async_ok",))
            done.set()

        try:
            store.submit(_task, ensure=[ddl])
            store.flush()

            assert done.wait(timeout=5), "Async write did not complete"

            # Verify the data
            with store.connection() as conn:
                result = conn.execute(f"SELECT event FROM {table_name}")
                if hasattr(result, "fetchall"):
                    rows = result.fetchall()
                else:
                    rows = list(result)
                assert len(rows) == 1
                # Access by column name (rows are dict-like after _mapping conversion)
                assert rows[0]["event"] == "async_ok"
        finally:
            store.shutdown(wait=True)
            # Clean up
            try:
                cleanup_store = TelemetryStore(
                    database=postgres_db_uri, async_writes=False
                )
                with cleanup_store.connection() as conn:
                    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                    conn.commit()
            except Exception:
                pass


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
class TestDDLAdaptation:
    """Test that DDL statements are adapted for PostgreSQL."""

    def test_postgres_ddl_adapted(self, postgres_db_uri):
        """Test that SQLite DDL is adapted for PostgreSQL."""
        store = TelemetryStore(database=postgres_db_uri, async_writes=False)

        # Test AUTOINCREMENT -> SERIAL conversion
        ddl = "CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        adapted = store._adapt_ddl(ddl)

        # PostgreSQL should use SERIAL
        assert "AUTOINCREMENT" not in adapted
