"""Deployment readiness tests for TelemetryStore SQLAlchemy migration.

These tests verify that the telemetry system is ready for production deployment
with PostgreSQL/Cloud SQL support.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.telemetry.store import TelemetryStore, get_store
from src.utils.byline_telemetry import BylineCleaningTelemetry
from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics,
)
from src.utils.content_cleaning_telemetry import ContentCleaningTelemetry


@pytest.fixture
def sqlite_store(tmp_path):
    """Create a SQLite store for testing."""
    db_path = tmp_path / "deployment_test.db"
    return TelemetryStore(database=f"sqlite:///{db_path}", async_writes=False)


@pytest.fixture
def postgres_url():
    """Get PostgreSQL URL from environment if available."""
    return os.getenv("TEST_DATABASE_URL")


class TestDeploymentReadiness:
    """Verify that telemetry system is ready for production deployment."""

    def test_sqlite_backward_compatibility(self, sqlite_store):
        """Verify SQLite still works exactly as before (backward compatibility)."""

        # Test basic operations
        def _task(conn):
            conn.execute("INSERT INTO test_table(value) VALUES (?)", ("test_value",))

        ddl = "CREATE TABLE IF NOT EXISTS test_table (value TEXT)"
        sqlite_store.submit(_task, ensure=[ddl])

        # Verify data was written
        with sqlite_store.connection() as conn:
            result = conn.execute("SELECT value FROM test_table")
            rows = result.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "test_value"

    def test_all_telemetry_classes_with_sqlite(self, sqlite_store):
        """Verify all telemetry classes work with SQLite."""
        # Test BylineCleaningTelemetry
        byline_telemetry = BylineCleaningTelemetry(store=sqlite_store)
        telemetry_id = byline_telemetry.start_cleaning_session(
            raw_byline="By Test Author",
            article_id="test-article-1",
        )
        byline_telemetry.finalize_cleaning_session(
            ["Test Author"],
            cleaning_method="test",
        )
        byline_telemetry.flush()
        assert telemetry_id

        # Test ContentCleaningTelemetry
        content_telemetry = ContentCleaningTelemetry(store=sqlite_store)
        session_id = content_telemetry.start_cleaning_session(
            domain="test.com",
            article_count=10,
        )
        content_telemetry.finalize_cleaning_session(
            rough_candidates_found=5,
            segments_detected=2,
            total_removable_chars=100,
            removal_percentage=10.0,
        )
        content_telemetry.flush()
        assert session_id

        # Test ComprehensiveExtractionTelemetry
        extraction_telemetry = ComprehensiveExtractionTelemetry(store=sqlite_store)
        metrics = ExtractionMetrics(
            "test-op-1", "test-article-2", "https://test.com/article", "test.com"
        )
        metrics.http_status_code = 200
        metrics.successful_method = "newspaper"
        # Set end time instead of calling end_extraction
        from datetime import datetime

        metrics.end_time = datetime.utcnow()
        extraction_telemetry.record_extraction(metrics)

        # Verify all data was written
        with sqlite_store.connection() as conn:
            # Check byline telemetry
            result = conn.execute("SELECT COUNT(*) FROM byline_cleaning_telemetry")
            count = result.fetchone()[0]
            assert count >= 1

            # Check content cleaning telemetry
            result = conn.execute("SELECT COUNT(*) FROM content_cleaning_sessions")
            count = result.fetchone()[0]
            assert count >= 1

            # Check extraction telemetry
            result = conn.execute("SELECT COUNT(*) FROM extraction_telemetry_v2")
            count = result.fetchone()[0]
            assert count >= 1

    @pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL")
        or "postgres" not in os.getenv("TEST_DATABASE_URL", ""),
        reason="PostgreSQL not configured for testing",
    )
    def test_postgresql_basic_operations(self, postgres_url):
        """Verify basic PostgreSQL operations work."""
        store = TelemetryStore(database=postgres_url, async_writes=False)

        # Clean up any existing test data
        import uuid

        table_name = f"test_deployment_{uuid.uuid4().hex[:8]}"

        try:
            # Create table and insert data
            def _task(conn):
                conn.execute(
                    f"INSERT INTO {table_name}(value) VALUES (?)", ("pg_test",)
                )

            ddl = f"CREATE TABLE IF NOT EXISTS {table_name} (id SERIAL PRIMARY KEY, value TEXT)"
            store.submit(_task, ensure=[ddl])

            # Verify data
            with store.connection() as conn:
                result = conn.execute(f"SELECT value FROM {table_name}")
                rows = result.fetchall()
                assert len(rows) >= 1
                assert rows[0][0] == "pg_test"

        finally:
            # Cleanup
            try:
                with store.connection() as conn:
                    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                    conn.commit()
            except Exception:
                pass

    @pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL")
        or "postgres" not in os.getenv("TEST_DATABASE_URL", ""),
        reason="PostgreSQL not configured for testing",
    )
    def test_postgresql_telemetry_classes(self, postgres_url):
        """Verify telemetry classes work with PostgreSQL."""
        import uuid

        # Use unique IDs to avoid conflicts
        test_id = uuid.uuid4().hex[:8]

        # Test with BylineCleaningTelemetry
        store = TelemetryStore(database=postgres_url, async_writes=False)
        byline_telemetry = BylineCleaningTelemetry(store=store)

        telemetry_id = byline_telemetry.start_cleaning_session(
            raw_byline=f"By Test Author {test_id}",
            article_id=f"pg-test-article-{test_id}",
        )
        byline_telemetry.finalize_cleaning_session(
            [f"Test Author {test_id}"],
            cleaning_method="postgresql_test",
        )
        byline_telemetry.flush()

        assert telemetry_id

        # Verify data was written to PostgreSQL
        with store.connection() as conn:
            result = conn.execute(
                "SELECT raw_byline FROM byline_cleaning_telemetry WHERE article_id = ?",
                (f"pg-test-article-{test_id}",),
            )
            rows = result.fetchall()
            assert len(rows) >= 1
            assert test_id in rows[0][0]

    def test_ddl_adaptation(self, sqlite_store):
        """Verify DDL adaptation works correctly."""
        # Test SQLite DDL (should remain unchanged or adapted correctly)
        sqlite_ddl = "CREATE TABLE IF NOT EXISTS test_auto (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        adapted = sqlite_store._adapt_ddl(sqlite_ddl)

        # For SQLite, it should work fine either way
        assert "PRIMARY KEY" in adapted

        # Create the table
        def _task(conn):
            pass  # Just ensure the table is created

        sqlite_store.submit(_task, ensure=[sqlite_ddl])

    def test_connection_wrapper_features(self, sqlite_store):
        """Verify connection wrapper provides all expected features."""
        with sqlite_store.connection() as conn:
            # Test execute with parameters
            conn.execute(
                "CREATE TABLE IF NOT EXISTS test_features (id INTEGER, name TEXT)"
            )
            conn.execute("INSERT INTO test_features VALUES (?, ?)", (1, "test"))

            # Test cursor interface
            cursor = conn.cursor()
            result = cursor.execute("SELECT * FROM test_features")

            # Test cursor.description
            assert hasattr(result, "description")
            assert result.description is not None

            # Test fetchone and fetchall
            rows = result.fetchall()
            assert len(rows) >= 1

    def test_async_writes(self, sqlite_store):
        """Verify async writes work correctly."""
        import threading
        import time

        # Create an async store
        async_store = TelemetryStore(
            database=sqlite_store.database_url, async_writes=True
        )

        done = threading.Event()

        def _task(conn):
            conn.execute("CREATE TABLE IF NOT EXISTS test_async (value TEXT)")
            conn.execute("INSERT INTO test_async VALUES (?)", ("async_test",))
            done.set()

        async_store.submit(_task)
        async_store.flush()

        # Wait for async write to complete
        assert done.wait(timeout=5), "Async write did not complete"

        # Verify data
        with async_store.connection() as conn:
            result = conn.execute("SELECT value FROM test_async")
            rows = result.fetchall()
            assert len(rows) >= 1
            assert rows[0][0] == "async_test"

        async_store.shutdown(wait=True)


class TestMigrationCompletion:
    """Verify that the migration is complete and ready for deployment."""

    def test_no_postgresql_blocks(self):
        """Verify PostgreSQL blocking checks have been removed."""
        # Check source files directly instead of trying to inspect property objects
        from pathlib import Path

        # Check byline_telemetry.py
        byline_file = Path("src/utils/byline_telemetry.py")
        byline_content = byline_file.read_text()
        assert (
            "does not support PostgreSQL" not in byline_content
        ), "PostgreSQL blocking check still exists in byline_telemetry"

        # Check content_cleaning_telemetry.py
        content_file = Path("src/utils/content_cleaning_telemetry.py")
        content_content = content_file.read_text()
        assert (
            "does not support PostgreSQL" not in content_content
        ), "PostgreSQL blocking check still exists in content_cleaning_telemetry"

    def test_alembic_migration_exists(self):
        """Verify Alembic migration for telemetry tables exists."""
        migration_file = Path(
            "alembic/versions/a9957c3054a4_add_remaining_telemetry_tables.py"
        )
        assert migration_file.exists(), "Alembic migration file not found"

        # Check that migration includes key tables
        content = migration_file.read_text()
        assert "byline_cleaning_telemetry" in content
        assert "content_cleaning_sessions" in content
        assert "persistent_boilerplate_patterns" in content

    def test_documentation_exists(self):
        """Verify migration documentation exists."""
        doc_file = Path("docs/TELEMETRY_STORE_SQLALCHEMY_MIGRATION.md")
        assert doc_file.exists(), "Migration documentation not found"

        content = doc_file.read_text()
        assert "SQLAlchemy" in content
        assert "PostgreSQL" in content
        assert "Deployment Checklist" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
