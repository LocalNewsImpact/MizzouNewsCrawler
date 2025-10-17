"""Tests for the migration smoke test script."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


class TestSmokeTestMigrations:
    """Test the smoke test script functionality."""

    def test_smoke_test_script_exists(self):
        """Test that smoke test script exists and is executable."""
        script_path = Path(__file__).parent.parent / "scripts" / "smoke_test_migrations.py"
        assert script_path.exists(), "Smoke test script not found"
        assert os.access(script_path, os.X_OK), "Smoke test script is not executable"

    def test_smoke_test_imports(self):
        """Test that smoke test script imports are valid."""
        # Add project root to path
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        # Try importing the smoke test module
        import scripts.smoke_test_migrations as smoke_test

        # Verify key functions exist
        assert hasattr(smoke_test, "get_database_url")
        assert hasattr(smoke_test, "check_table_exists")
        assert hasattr(smoke_test, "get_missing_tables")
        assert hasattr(smoke_test, "check_alembic_version")
        assert hasattr(smoke_test, "main")

    @patch("scripts.smoke_test_migrations.create_engine")
    @patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"})
    def test_get_database_url_from_env(self, mock_create_engine):
        """Test getting database URL from DATABASE_URL env var."""
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        from scripts.smoke_test_migrations import get_database_url

        url = get_database_url()
        assert url == "sqlite:///:memory:"

    @patch("scripts.smoke_test_migrations.create_engine")
    @patch.dict(
        os.environ,
        {
            "USE_CLOUD_SQL_CONNECTOR": "true",
            "CLOUD_SQL_INSTANCE": "project:region:instance",
            "DATABASE_USER": "testuser",
            "DATABASE_PASSWORD": "testpass",
            "DATABASE_NAME": "testdb",
        },
        clear=True,
    )
    def test_get_database_url_from_cloud_sql(self, mock_create_engine):
        """Test getting database URL from Cloud SQL env vars."""
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        from scripts.smoke_test_migrations import get_database_url

        url = get_database_url()
        assert "postgresql+pg8000" in url
        assert "testuser" in url
        assert "testpass" in url
        assert "testdb" in url
        assert "project:region:instance" in url

    def test_check_table_exists(self):
        """Test table existence checking."""
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        from scripts.smoke_test_migrations import check_table_exists

        # Create mock inspector
        mock_inspector = Mock()
        mock_inspector.get_table_names.return_value = ["table1", "table2", "table3"]

        # Test existing table
        assert check_table_exists(mock_inspector, "table1") is True

        # Test non-existing table
        assert check_table_exists(mock_inspector, "table4") is False

    def test_get_missing_tables(self):
        """Test getting missing tables."""
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        from scripts.smoke_test_migrations import get_missing_tables

        # Create mock inspector
        mock_inspector = Mock()
        mock_inspector.get_table_names.return_value = ["table1", "table2"]

        expected_tables = {"table1", "table2", "table3"}
        missing = get_missing_tables(mock_inspector, expected_tables)

        assert missing == {"table3"}

    @pytest.mark.integration
    def test_smoke_test_with_real_database(self, tmp_path):
        """Integration test: Run smoke test against a real SQLite database with migrations."""
        # Create temp SQLite database
        db_path = tmp_path / "test_smoke.db"
        database_url = f"sqlite:///{db_path}"

        # Set environment variable for Alembic
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"

        project_root = Path(__file__).parent.parent

        # First, run migrations to create tables
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        assert result.returncode == 0, f"Migration failed: {result.stderr}"

        # Now run smoke test
        result = subprocess.run(
            ["python3", "scripts/smoke_test_migrations.py"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )

        # Check that smoke test passed
        assert result.returncode == 0, f"Smoke test failed: {result.stderr}\n{result.stdout}"
        assert "All smoke tests passed" in result.stdout

    @pytest.mark.integration
    def test_smoke_test_fails_on_missing_tables(self, tmp_path):
        """Integration test: Smoke test should fail if tables are missing."""
        # Create temp SQLite database without running migrations
        db_path = tmp_path / "test_empty.db"
        database_url = f"sqlite:///{db_path}"

        # Create empty database file
        db_path.touch()

        # Set environment variable
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        env["USE_CLOUD_SQL_CONNECTOR"] = "false"

        project_root = Path(__file__).parent.parent

        # Run smoke test on empty database (should fail)
        result = subprocess.run(
            ["python3", "scripts/smoke_test_migrations.py"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )

        # Should fail with exit code 3 (validation error)
        assert result.returncode != 0, "Smoke test should fail on empty database"
        # Could be exit code 3 (validation error) or 2 (connection error)
        assert result.returncode in (2, 3)
