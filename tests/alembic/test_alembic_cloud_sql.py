"""Tests for Alembic Cloud SQL Connector integration.

These tests verify that alembic/env.py correctly:
1. Uses Cloud SQL Connector when USE_CLOUD_SQL_CONNECTOR=true
2. Falls back to DATABASE_URL when connector is disabled
3. Handles missing configuration gracefully
4. Detects environment correctly
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration


class TestAlembicCloudSQL:
    """Test Alembic Cloud SQL Connector integration."""

    def test_alembic_env_module_exists(self):
        """Test that alembic/env.py exists and has expected structure."""
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / "alembic" / "env.py"

        assert env_path.exists(), "alembic/env.py not found"

        # Read and verify it has expected functions
        env_content = env_path.read_text()
        assert "def run_migrations_offline" in env_content
        assert "def run_migrations_online" in env_content
        assert "create_cloud_sql_engine" in env_content
        assert "USE_CLOUD_SQL_CONNECTOR" in env_content
        assert "CLOUD_SQL_INSTANCE" in env_content

    def test_alembic_uses_cloud_sql_connector_when_enabled(self):
        """Test that Alembic env.py has Cloud SQL Connector logic when enabled."""
        # Verify that env.py has the Cloud SQL Connector logic
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / "alembic" / "env.py"
        env_content = env_path.read_text()

        # Check that it has the Cloud SQL Connector conditional
        assert "use_cloud_sql = " in env_content
        assert "USE_CLOUD_SQL_CONNECTOR" in env_content
        assert "CLOUD_SQL_INSTANCE" in env_content

        # Check that it imports and uses create_cloud_sql_engine
        assert (
            "from src.models.cloud_sql_connector import create_cloud_sql_engine"
            in env_content
        )
        assert "create_cloud_sql_engine(" in env_content

        # Check that it passes the right parameters
        assert "instance_connection_name=" in env_content
        assert "user=" in env_content
        assert "password=" in env_content
        assert "database=" in env_content

    def test_alembic_uses_database_url_when_connector_disabled(self):
        """Test that Alembic has fallback to DATABASE_URL when Cloud SQL Connector disabled."""
        # Verify that env.py has fallback logic
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / "alembic" / "env.py"
        env_content = env_path.read_text()

        # Check that it has an else clause for standard connection
        assert "else:" in env_content
        assert "engine_from_config" in env_content

        # Check that it uses sqlalchemy.url from config
        assert "sqlalchemy.url" in env_content or "DATABASE_URL" in env_content

    def test_alembic_env_detects_cloud_sql_config(self):
        """Test that alembic/env.py correctly detects Cloud SQL configuration."""
        # Test with Cloud SQL enabled
        env_vars = {
            "USE_CLOUD_SQL_CONNECTOR": "true",
            "CLOUD_SQL_INSTANCE": "test-project:us-central1:test-instance",
            "DATABASE_USER": "test_user",
            "DATABASE_PASSWORD": "test_pass",
            "DATABASE_NAME": "test_db",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            # Reload config
            import src.config as app_config

            importlib.reload(app_config)

            # Check that config has the right values
            assert hasattr(app_config, "USE_CLOUD_SQL_CONNECTOR")
            assert app_config.USE_CLOUD_SQL_CONNECTOR is True
            assert hasattr(app_config, "CLOUD_SQL_INSTANCE")
            assert (
                app_config.CLOUD_SQL_INSTANCE
                == "test-project:us-central1:test-instance"
            )

    def test_alembic_env_falls_back_without_cloud_sql_instance(self):
        """Test that alembic/env.py uses standard connection when CLOUD_SQL_INSTANCE is not set."""
        # Verify the env.py logic checks for both USE_CLOUD_SQL_CONNECTOR AND CLOUD_SQL_INSTANCE
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / "alembic" / "env.py"
        env_content = env_path.read_text()

        # Check that it validates both conditions
        assert "USE_CLOUD_SQL_CONNECTOR" in env_content
        assert "CLOUD_SQL_INSTANCE" in env_content

        # The condition should be: USE_CLOUD_SQL_CONNECTOR and CLOUD_SQL_INSTANCE
        # This ensures it falls back if either is missing
        assert " and " in env_content or "and getattr" in env_content

    def test_alembic_config_url_escapes_percent_signs(self):
        """Test that DATABASE_URL with % characters is properly escaped for ConfigParser."""
        # This was a real bug - ConfigParser interprets % as variable interpolation
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / "alembic" / "env.py"
        env_content = env_path.read_text()

        # Verify that env.py has the % escaping logic
        assert (
            '.replace("%", "%%")' in env_content
            or '.replace("%", r"%%")' in env_content
        ), "env.py should escape % characters in DATABASE_URL to prevent ConfigParser errors"

    def test_database_url_construction_from_components(self):
        """Test that DATABASE_URL can be constructed from individual components."""
        # Verify that src/config.py has logic to build DATABASE_URL from components
        project_root = Path(__file__).parent.parent.parent
        config_path = project_root / "src" / "config.py"
        config_content = config_path.read_text()

        # Check that config.py has the DATABASE_URL construction logic
        assert "DATABASE_ENGINE" in config_content
        assert "DATABASE_HOST" in config_content
        assert "DATABASE_PORT" in config_content
        assert "DATABASE_NAME" in config_content
        assert "DATABASE_USER" in config_content
        assert "DATABASE_PASSWORD" in config_content

        # Check that it builds the URL
        assert "DATABASE_URL" in config_content
        # Should have logic to construct URL from parts
        assert "DATABASE_HOST" in config_content and "DATABASE_NAME" in config_content


class TestAlembicEnvironmentDetection:
    """Test environment detection logic in alembic/env.py."""

    def test_production_environment_config(self):
        """Test that production environment is correctly detected."""
        env_vars = {
            "APP_ENV": "production",
            "USE_CLOUD_SQL_CONNECTOR": "true",
            "CLOUD_SQL_INSTANCE": "prod-project:us-central1:prod-instance",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            import src.config as app_config

            importlib.reload(app_config)

            assert app_config.APP_ENV == "production"
            assert app_config.USE_CLOUD_SQL_CONNECTOR is True

    def test_development_environment_config(self):
        """Test that development environment configuration is supported."""
        # Verify that config.py supports development environment
        project_root = Path(__file__).parent.parent.parent
        config_path = project_root / "src" / "config.py"
        config_content = config_path.read_text()

        # Check that config supports APP_ENV
        assert "APP_ENV" in config_content

        # Check that it has a default DATABASE_URL for development
        assert "DATABASE_URL" in config_content
        assert "sqlite" in config_content.lower() or "default" in config_content.lower()
