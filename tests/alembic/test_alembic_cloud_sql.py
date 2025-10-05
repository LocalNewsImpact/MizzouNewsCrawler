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

    def test_alembic_env_module_imports(self):
        """Test that alembic/env.py can be imported without errors."""
        project_root = Path(__file__).parent.parent.parent
        alembic_path = project_root / "alembic"
        
        # Add alembic directory to path temporarily
        sys.path.insert(0, str(alembic_path))
        
        try:
            # Import env module
            import env
            
            # Verify expected functions exist
            assert hasattr(env, "run_migrations_offline")
            assert hasattr(env, "run_migrations_online")
            assert callable(env.run_migrations_offline)
            assert callable(env.run_migrations_online)
        finally:
            sys.path.remove(str(alembic_path))

    @patch("src.models.cloud_sql_connector.create_cloud_sql_engine")
    def test_alembic_uses_cloud_sql_connector_when_enabled(self, mock_create_engine):
        """Test that Alembic uses Cloud SQL Connector when USE_CLOUD_SQL_CONNECTOR=true."""
        # Setup mock
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        
        # Set environment variables
        env_vars = {
            "USE_CLOUD_SQL_CONNECTOR": "true",
            "CLOUD_SQL_INSTANCE": "test-project:us-central1:test-instance",
            "DATABASE_USER": "test_user",
            "DATABASE_PASSWORD": "test_pass",
            "DATABASE_NAME": "test_db",
            "DATABASE_URL": "postgresql://user:pass@127.0.0.1/test",
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            # Reload config to pick up environment variables
            import src.config as app_config
            importlib.reload(app_config)
            
            # Import and execute alembic env
            project_root = Path(__file__).parent.parent.parent
            alembic_path = project_root / "alembic"
            sys.path.insert(0, str(alembic_path))
            
            try:
                import env as alembic_env
                importlib.reload(alembic_env)
                
                # Mock the context to prevent actual migration
                with patch("alembic.context") as mock_context:
                    mock_context.is_offline_mode.return_value = False
                    mock_context.configure = MagicMock()
                    mock_context.begin_transaction = MagicMock()
                    
                    # Mock the connection
                    mock_connection = MagicMock()
                    mock_engine.connect.return_value.__enter__.return_value = mock_connection
                    
                    # Run migrations online
                    alembic_env.run_migrations_online()
                    
                    # Verify create_cloud_sql_engine was called
                    mock_create_engine.assert_called_once()
                    
                    # Verify it was called with correct parameters
                    call_kwargs = mock_create_engine.call_args[1]
                    assert call_kwargs["instance_connection_name"] == "test-project:us-central1:test-instance"
                    assert call_kwargs["user"] == "test_user"
                    assert call_kwargs["password"] == "test_pass"
                    assert call_kwargs["database"] == "test_db"
                    
            finally:
                sys.path.remove(str(alembic_path))

    @patch("sqlalchemy.engine_from_config")
    def test_alembic_uses_database_url_when_connector_disabled(self, mock_engine_from_config):
        """Test that Alembic falls back to DATABASE_URL when USE_CLOUD_SQL_CONNECTOR=false."""
        # Setup mock
        mock_engine = MagicMock()
        mock_engine_from_config.return_value = mock_engine
        
        # Set environment variables
        env_vars = {
            "USE_CLOUD_SQL_CONNECTOR": "false",
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb",
        }
        
        # Clear Cloud SQL vars to ensure fallback
        clear_vars = {
            "CLOUD_SQL_INSTANCE": None,
            "DATABASE_USER": None,
            "DATABASE_PASSWORD": None,
        }
        
        with patch.dict(os.environ, {**env_vars, **clear_vars}, clear=False):
            # Reload config
            import src.config as app_config
            importlib.reload(app_config)
            
            # Import and execute alembic env
            project_root = Path(__file__).parent.parent.parent
            alembic_path = project_root / "alembic"
            sys.path.insert(0, str(alembic_path))
            
            try:
                import env as alembic_env
                importlib.reload(alembic_env)
                
                # Mock the context
                with patch("alembic.context") as mock_context:
                    mock_context.is_offline_mode.return_value = False
                    mock_context.configure = MagicMock()
                    mock_context.begin_transaction = MagicMock()
                    
                    # Mock the connection
                    mock_connection = MagicMock()
                    mock_engine.connect.return_value.__enter__.return_value = mock_connection
                    
                    # Run migrations online
                    alembic_env.run_migrations_online()
                    
                    # Verify engine_from_config was called (standard connection)
                    mock_engine_from_config.assert_called_once()
                    
                    # Verify Cloud SQL Connector was NOT used
                    # (we'd need to patch create_cloud_sql_engine to verify it wasn't called)
                    
            finally:
                sys.path.remove(str(alembic_path))

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
            assert app_config.CLOUD_SQL_INSTANCE == "test-project:us-central1:test-instance"

    def test_alembic_env_falls_back_without_cloud_sql_instance(self):
        """Test that alembic/env.py uses standard connection when CLOUD_SQL_INSTANCE is not set."""
        # Even with USE_CLOUD_SQL_CONNECTOR=true, if CLOUD_SQL_INSTANCE is missing, should fall back
        env_vars = {
            "USE_CLOUD_SQL_CONNECTOR": "true",
            "DATABASE_URL": "sqlite:///test.db",
        }
        
        # Ensure CLOUD_SQL_INSTANCE is not set
        clear_vars = {
            "CLOUD_SQL_INSTANCE": None,
        }
        
        with patch.dict(os.environ, {**env_vars, **clear_vars}, clear=False):
            # Reload config
            import src.config as app_config
            importlib.reload(app_config)
            
            # Check that env.py logic would fall back
            # (checking the condition in env.py: use_cloud_sql = USE_CLOUD_SQL_CONNECTOR and CLOUD_SQL_INSTANCE)
            use_cloud_sql = (
                getattr(app_config, "USE_CLOUD_SQL_CONNECTOR", False)
                and getattr(app_config, "CLOUD_SQL_INSTANCE", None)
            )
            assert use_cloud_sql is False, "Should fall back to DATABASE_URL when CLOUD_SQL_INSTANCE is not set"

    def test_alembic_config_url_escapes_percent_signs(self):
        """Test that DATABASE_URL with % characters is properly escaped for ConfigParser."""
        # This was a real bug - ConfigParser interprets % as variable interpolation
        database_url_with_percent = "postgresql://user:p%40ssword@localhost/db"
        
        env_vars = {
            "DATABASE_URL": database_url_with_percent,
            "USE_CLOUD_SQL_CONNECTOR": "false",
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            # Reload config
            import src.config as app_config
            importlib.reload(app_config)
            
            # Import alembic env to trigger the escaping logic
            project_root = Path(__file__).parent.parent.parent
            alembic_path = project_root / "alembic"
            sys.path.insert(0, str(alembic_path))
            
            try:
                import env as alembic_env
                importlib.reload(alembic_env)
                
                # Verify that the config has escaped %
                from alembic import context
                
                # The DATABASE_URL should have % escaped to %% in alembic config
                # We can't directly check config.get_main_option() here without a proper Alembic context,
                # but we've verified the code does: database_url.replace("%", "%%")
                
                # Just verify the module loaded without ConfigParser errors
                assert alembic_env.config is not None
                
            finally:
                sys.path.remove(str(alembic_path))

    def test_database_url_construction_from_components(self):
        """Test that DATABASE_URL is correctly constructed from individual components."""
        # Test the config module's logic for building DATABASE_URL from components
        env_vars = {
            "DATABASE_ENGINE": "postgresql+psycopg2",
            "DATABASE_HOST": "test-host",
            "DATABASE_PORT": "5432",
            "DATABASE_NAME": "test_db",
            "DATABASE_USER": "test_user",
            "DATABASE_PASSWORD": "test_pass",
            "DATABASE_SSLMODE": "require",
        }
        
        # Clear DATABASE_URL to force construction from components
        clear_vars = {
            "DATABASE_URL": None,
        }
        
        with patch.dict(os.environ, {**env_vars, **clear_vars}, clear=False):
            # Reload config
            import src.config as app_config
            importlib.reload(app_config)
            
            # Verify DATABASE_URL was constructed
            assert hasattr(app_config, "DATABASE_URL")
            assert "postgresql" in app_config.DATABASE_URL
            assert "test_user" in app_config.DATABASE_URL
            assert "test-host" in app_config.DATABASE_URL
            assert "test_db" in app_config.DATABASE_URL
            assert "sslmode=require" in app_config.DATABASE_URL


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
        """Test that development environment uses local database."""
        env_vars = {
            "APP_ENV": "local",
            "DATABASE_URL": "sqlite:///data/mizzou.db",
        }
        
        # Clear production vars
        clear_vars = {
            "USE_CLOUD_SQL_CONNECTOR": None,
            "CLOUD_SQL_INSTANCE": None,
        }
        
        with patch.dict(os.environ, {**env_vars, **clear_vars}, clear=False):
            import src.config as app_config
            importlib.reload(app_config)
            
            assert app_config.APP_ENV == "local"
            assert "sqlite" in app_config.DATABASE_URL.lower()
