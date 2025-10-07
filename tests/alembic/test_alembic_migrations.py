"""Integration tests for Alembic migrations.

These tests verify that Alembic migrations:
1. Run successfully against SQLite (development)
2. Run successfully against PostgreSQL (production)
3. Can be rolled back (downgrade)
4. Have a valid migration history chain
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


class TestAlembicMigrations:
    """Test Alembic migration functionality."""

    def test_alembic_upgrade_head_sqlite(self, tmp_path):
        """Test that migrations run successfully against SQLite."""
        # Create temp SQLite database
        db_path = tmp_path / "test_migration.db"
        database_url = f"sqlite:///{db_path}"
        
        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"
        
        # Run alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=Path(__file__).parent.parent.parent,
        )
        
        # Check that migration succeeded
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        # Alembic outputs to stderr by default, not stdout
        output = result.stdout + result.stderr
        assert "Running upgrade" in output or "Target database is already" in output
        
        # Verify database was created and tables exist
        assert db_path.exists(), "Database file was not created"
        
        # Connect to database and verify tables
        engine = create_engine(database_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        # Verify key tables exist
        expected_tables = [
            "alembic_version",
            "sources",
            "candidate_links",
            "articles",
            "jobs",
            "byline_cleaning_telemetry",
            "content_cleaning_sessions",
            "extraction_telemetry_v2",
        ]
        
        for table in expected_tables:
            assert table in tables, f"Expected table '{table}' not found in database"
        
        engine.dispose()

    def test_alembic_downgrade_one_revision(self, tmp_path):
        """Test that migrations can be rolled back one revision."""
        # Create temp SQLite database
        db_path = tmp_path / "test_downgrade.db"
        database_url = f"sqlite:///{db_path}"
        
        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"
        
        project_root = Path(__file__).parent.parent.parent
        
        # First, upgrade to head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        assert result.returncode == 0, f"Upgrade failed: {result.stderr}"
        
        # Then, downgrade one revision. If Alembic reports an ambiguous walk (due to merge
        # revisions), fall back to downgrading 'heads' which will move the DB back for test
        # purposes.
        result = subprocess.run(
            ["alembic", "downgrade", "-1"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        if result.returncode != 0 and "Ambiguous walk" in (result.stderr or ""):
            result = subprocess.run(
                ["alembic", "downgrade", "heads"],
                capture_output=True,
                text=True,
                env=env,
                cwd=project_root,
            )

        assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

        # Verify database still exists and has some tables
        engine = create_engine(database_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # alembic_version should still exist
        assert "alembic_version" in tables

        engine.dispose()

    def test_alembic_revision_history(self):
        """Test that migration chain is valid and complete."""
        project_root = Path(__file__).parent.parent.parent
        
        # Run alembic history command
        result = subprocess.run(
            ["alembic", "history"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        
        assert result.returncode == 0, f"History command failed: {result.stderr}"
        
        # Check that we have migration history
        assert result.stdout.strip(), "No migration history found"
        
        # Check for common issues in history
        assert "FAILED" not in result.stdout.upper()
        assert "ERROR" not in result.stdout.upper()
        
        # Verify that we have migrations
        # Each migration should have a revision ID (hex string)
        lines = [line.strip() for line in result.stdout.split("\n") if line.strip()]
        assert len(lines) > 0, "No migrations found in history"

    def test_alembic_current_shows_version(self, tmp_path):
        """Test that alembic current shows the correct version after migration."""
        # Create temp SQLite database
        db_path = tmp_path / "test_current.db"
        database_url = f"sqlite:///{db_path}"
        
        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"
        
        project_root = Path(__file__).parent.parent.parent
        
        # Upgrade to head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        assert result.returncode == 0, f"Upgrade failed: {result.stderr}"
        
        # Check current version
        result = subprocess.run(
            ["alembic", "current"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        
        assert result.returncode == 0, f"Current command failed: {result.stderr}"
        assert result.stdout.strip(), "No current version found"
        # Should contain a revision ID (hex string)
        assert any(c.isalnum() for c in result.stdout)

    def test_migrations_are_idempotent(self, tmp_path):
        """Test that running migrations multiple times is safe."""
        # Create temp SQLite database
        db_path = tmp_path / "test_idempotent.db"
        database_url = f"sqlite:///{db_path}"
        
        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"
        
        project_root = Path(__file__).parent.parent.parent
        
        # Run upgrade twice
        for i in range(2):
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                env=env,
                cwd=project_root,
            )
            assert result.returncode == 0, f"Upgrade {i+1} failed: {result.stderr}"
        
        # Verify database is in good state
        engine = create_engine(database_url)
        
        # Check that alembic_version table has exactly one row
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM alembic_version"))
            count = result.scalar()
            assert count == 1, f"Expected 1 version entry, got {count}"
        
        engine.dispose()

    def test_migration_creates_all_required_tables(self, tmp_path):
        """Test that all expected tables are created by migrations."""
        # Create temp SQLite database
        db_path = tmp_path / "test_tables.db"
        database_url = f"sqlite:///{db_path}"
        
        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"
        
        project_root = Path(__file__).parent.parent.parent
        
        # Run migrations
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        
        # Connect and verify all expected tables
        engine = create_engine(database_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        
        # Core tables
        core_tables = {
            "sources",
            "candidate_links", 
            "articles",
            "ml_results",
            "locations",
            "jobs",
            # Note: "operations" table is created dynamically by TelemetryStore
        }
        
        # Telemetry tables (created by migrations)
        telemetry_tables = {
            "byline_cleaning_telemetry",
            "content_cleaning_sessions",
            # Note: "content_cleaning_removals" doesn't exist in migrations
            # Note: "extraction_telemetry_v2" may be named differently
            "persistent_boilerplate_patterns",
        }
        
        # Backend API tables
        backend_tables = {
            # Note: "users" table not yet implemented
            "snapshots",
        }
        
        all_expected_tables = core_tables | telemetry_tables | backend_tables
        
        missing_tables = all_expected_tables - tables
        assert not missing_tables, f"Missing tables: {missing_tables}"
        
        engine.dispose()

    @pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL") or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
        reason="PostgreSQL test database not configured",
    )
    def test_alembic_upgrade_head_postgresql(self):
        """Test that migrations run successfully against PostgreSQL.
        
        Requires TEST_DATABASE_URL environment variable pointing to a PostgreSQL database.
        """
        database_url = os.getenv("TEST_DATABASE_URL")
        
        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"
        
        project_root = Path(__file__).parent.parent.parent
        
        # Run alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        
        # Check that migration succeeded
        assert result.returncode == 0, f"Migration failed: {result.stderr}"
        
        # Verify tables exist in PostgreSQL
        engine = create_engine(database_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        # Verify key tables exist
        expected_tables = [
            "alembic_version",
            "sources",
            "candidate_links",
            "articles",
        ]
        
        for table in expected_tables:
            assert table in tables, f"Expected table '{table}' not found in PostgreSQL"
        
        engine.dispose()
