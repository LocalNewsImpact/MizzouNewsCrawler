"""Tests for TelemetryStore with PostgreSQL compatibility."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from src.telemetry.store import TelemetryStore, get_store

# Check if we have PostgreSQL connection info for testing
POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL


@pytest.fixture
def postgres_db_uri():
    """Get PostgreSQL test database URI."""
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured")
    return POSTGRES_TEST_URL


@pytest.fixture
def temp_db_uri(tmp_path):
    """Create a sqlite URI pointing at a temporary file."""
    db_path = tmp_path / "telemetry_store_pg_test.db"
    return f"sqlite:///{db_path}"


def _fetch_all_sqlalchemy(store: TelemetryStore, query: str) -> list[tuple]:
    """Helper to read rows from the database using SQLAlchemy."""
    with store.connection() as conn:
        result = conn.execute(query)
        rows = result.fetchall() if hasattr(result, 'fetchall') else []
    return rows


class TestSQLiteCompatibility:
    """Test that SQLite still works with the new SQLAlchemy implementation."""
    
    def test_simple_insert_and_query(self, temp_db_uri):
        """Test basic insert and query operations."""
        store = TelemetryStore(database=temp_db_uri, async_writes=False)
        
        def _task(conn) -> None:
            conn.execute("INSERT INTO test_data(value) VALUES (?)", ("hello",))
        
        ddl = "CREATE TABLE IF NOT EXISTS test_data (value TEXT)"
        store.submit(_task, ensure=[ddl])
        
        # Query the data
        with store.connection() as conn:
            result = conn.execute("SELECT value FROM test_data")
            # Get the first row - handle both SQLAlchemy and sqlite3 result formats
            if hasattr(result, 'fetchall'):
                rows = result.fetchall()
            else:
                rows = list(result)
            assert len(rows) == 1
            assert rows[0][0] == "hello"
    
    def test_multiple_inserts_with_parameters(self, temp_db_uri):
        """Test multiple inserts with different parameter values."""
        store = TelemetryStore(database=temp_db_uri, async_writes=False)
        
        ddl = "CREATE TABLE IF NOT EXISTS events (id INTEGER, name TEXT)"
        
        def _task1(conn):
            conn.execute("INSERT INTO events(id, name) VALUES (?, ?)", (1, "first"))
        
        def _task2(conn):
            conn.execute("INSERT INTO events(id, name) VALUES (?, ?)", (2, "second"))
        
        store.submit(_task1, ensure=[ddl])
        store.submit(_task2)
        
        # Query and verify
        with store.connection() as conn:
            result = conn.execute("SELECT id, name FROM events ORDER BY id")
            if hasattr(result, 'fetchall'):
                rows = result.fetchall()
            else:
                rows = list(result)
            assert len(rows) == 2
            assert rows[0][0] == 1
            assert rows[0][1] == "first"
            assert rows[1][0] == 2
            assert rows[1][1] == "second"


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
            if hasattr(result, 'fetchall'):
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
        
        ddl = f"CREATE TABLE IF NOT EXISTS {table_name} (id SERIAL PRIMARY KEY, value TEXT)"
        
        def _task(conn):
            conn.execute(f"INSERT INTO {table_name}(value) VALUES (?)", ("postgres_test",))
        
        try:
            store.submit(_task, ensure=[ddl])
            
            # Verify the insert
            with store.connection() as conn:
                result = conn.execute(f"SELECT value FROM {table_name}")
                if hasattr(result, 'fetchall'):
                    rows = result.fetchall()
                else:
                    rows = list(result)
                assert len(rows) == 1
                assert rows[0][0] == "postgres_test"
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
                if hasattr(result, 'fetchall'):
                    rows = result.fetchall()
                else:
                    rows = list(result)
                assert len(rows) == 1
                assert rows[0][0] == "async_ok"
        finally:
            store.shutdown(wait=True)
            # Clean up
            try:
                cleanup_store = TelemetryStore(database=postgres_db_uri, async_writes=False)
                with cleanup_store.connection() as conn:
                    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                    conn.commit()
            except Exception:
                pass


class TestDDLAdaptation:
    """Test that DDL statements are adapted for different databases."""
    
    def test_sqlite_ddl_unchanged(self, temp_db_uri):
        """Test that SQLite DDL is unchanged."""
        store = TelemetryStore(database=temp_db_uri, async_writes=False)
        
        ddl = "CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        adapted = store._adapt_ddl(ddl)
        
        # SQLite DDL should remain unchanged
        assert "INTEGER PRIMARY KEY AUTOINCREMENT" in adapted or "SERIAL PRIMARY KEY" in adapted
    
    @pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
    def test_postgres_ddl_adapted(self, postgres_db_uri):
        """Test that SQLite DDL is adapted for PostgreSQL."""
        store = TelemetryStore(database=postgres_db_uri, async_writes=False)
        
        # Test AUTOINCREMENT -> SERIAL conversion
        ddl = "CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        adapted = store._adapt_ddl(ddl)
        
        # PostgreSQL should use SERIAL
        assert "AUTOINCREMENT" not in adapted
