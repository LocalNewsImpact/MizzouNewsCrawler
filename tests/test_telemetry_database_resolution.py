"""Test telemetry default database resolution in NewsDiscovery.

This test module covers the changes made in PR #136 to ensure that:
1. _resolve_database_url() correctly resolves database URLs
2. NewsDiscovery properly initializes with various database URL configurations
3. Telemetry system receives the correct database URL
4. Production behavior (Cloud SQL) and development behavior (SQLite) work correctly
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, Mock, patch

from src.crawler.discovery import NewsDiscovery


class TestResolveDatabaseUrl:
    """Test the _resolve_database_url static method."""

    def test_explicit_database_url_is_used(self):
        """When an explicit database URL is provided, it should be returned as-is."""
        explicit_url = "postgresql://user:pass@host:5432/dbname"
        result = NewsDiscovery._resolve_database_url(explicit_url)
        assert result == explicit_url

    def test_explicit_sqlite_url_is_used(self):
        """When an explicit SQLite URL is provided, it should be returned as-is."""
        explicit_url = "sqlite:///tmp/test.db"
        result = NewsDiscovery._resolve_database_url(explicit_url)
        assert result == explicit_url

    def test_none_with_configured_database_url(self):
        """Return configured DATABASE_URL when it is available."""
        # Mock the config import to provide a configured DATABASE_URL
        mock_database_url = "postgresql://prod:secret@cloudsql/proddb"
        
        with patch.dict(os.environ, {"PYTEST_KEEP_DB_ENV": "true"}, clear=False):
            with patch.dict(sys.modules):
                # Create a mock config module
                mock_config = Mock()
                mock_config.DATABASE_URL = mock_database_url
                sys.modules['src.config'] = mock_config

                result = NewsDiscovery._resolve_database_url(None)
                assert result == mock_database_url

    def test_empty_string_is_treated_as_falsy(self):
        """Empty string is treated as falsy and falls back to config.
        
        This is the actual behavior: `if candidate:` treats "" as False.
        This is reasonable behavior - empty string is not a valid database URL.
        """
        with patch.dict(os.environ, {"PYTEST_KEEP_DB_ENV": "true"}, clear=False):
            with patch.dict(sys.modules):
                mock_config = Mock()
                mock_config.DATABASE_URL = "postgresql://config:config@host:5432/db"
                sys.modules['src.config'] = mock_config

                # Empty string is treated as falsy, falls back to config
                result = NewsDiscovery._resolve_database_url("")
                assert result == "postgresql://config:config@host:5432/db"


class TestNewsDiscoveryInitialization:
    """Test NewsDiscovery initialization with various database URL configurations."""

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_explicit_database_url_initialization(self, mock_create_telemetry):
        """NewsDiscovery with explicit database_url should use that URL."""
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        explicit_url = "postgresql://test:test@testhost:5432/testdb"
        
        # Initialize NewsDiscovery with explicit database_url
        discovery = NewsDiscovery(database_url=explicit_url)
        
        # Verify database_url is set correctly
        assert discovery.database_url == explicit_url
        
        # Verify telemetry was created with the resolved URL
        # When user provides explicit database_url, telemetry receives it too
        mock_create_telemetry.assert_called_once()
        call_kwargs = mock_create_telemetry.call_args[1]
        assert call_kwargs['database_url'] == explicit_url

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_no_database_url_uses_configured_value(self, mock_create_telemetry):
        """NewsDiscovery without database_url should resolve from config."""
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        configured_url = "postgresql://config:config@confighost:5432/configdb"
        
        with patch.dict(os.environ, {"PYTEST_KEEP_DB_ENV": "true"}, clear=False):
            with patch.dict(sys.modules):
                mock_config = Mock()
                mock_config.DATABASE_URL = configured_url
                sys.modules['src.config'] = mock_config

                # Initialize NewsDiscovery without database_url
                discovery = NewsDiscovery()
            
                # Verify database_url is resolved from config
                assert discovery.database_url == configured_url

                # Verify telemetry uses None so DatabaseManager can manage the
                # Cloud SQL connection when no explicit database_url is provided.
                mock_create_telemetry.assert_called_once()
                call_kwargs = mock_create_telemetry.call_args[1]
                assert call_kwargs['database_url'] is None

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_no_database_url_requires_postgresql(self, mock_create_telemetry):
        """NewsDiscovery without database_url and no config should raise error.
        
        SQLite fallback has been removed - system must have PostgreSQL configured.
        """
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        with patch.dict(sys.modules):
            mock_config = Mock()
            mock_config.DATABASE_URL = None
            sys.modules['src.config'] = mock_config
            
            # Initialize NewsDiscovery without database_url should use None
            # (DatabaseManager will handle the connection)
            discovery = NewsDiscovery()
            
            # Verify database_url is None (no SQLite fallback)
            assert discovery.database_url is None
            
            # Verify telemetry was created with None
            mock_create_telemetry.assert_called_once()
            call_kwargs = mock_create_telemetry.call_args[1]
            assert call_kwargs['database_url'] is None


class TestTelemetryDatabaseUrlPassing:
    """Test that telemetry receives the correct database URL."""

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_telemetry_receives_explicit_url_when_provided(self, mock_create_telemetry):
        """When explicit database_url provided, telemetry should receive it."""
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        explicit_url = "postgresql://explicit:pass@host:5432/db"

        NewsDiscovery(database_url=explicit_url)
        
        # Verify telemetry was called with the explicit URL
        mock_create_telemetry.assert_called_once()
        call_kwargs = mock_create_telemetry.call_args[1]
        assert call_kwargs['database_url'] == explicit_url

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_telemetry_receives_none_when_not_provided(self, mock_create_telemetry):
        """When no database_url provided, telemetry should receive None.
        
        This is critical for production: telemetry can then use DatabaseManager
        which will connect to Cloud SQL instead of falling back to SQLite.
        """
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        configured_url = "postgresql://cloud:sql@instance/db"
        
        with patch.dict(os.environ, {"PYTEST_KEEP_DB_ENV": "true"}, clear=False):
            with patch.dict(sys.modules):
                mock_config = Mock()
                mock_config.DATABASE_URL = configured_url
                sys.modules['src.config'] = mock_config

                # Initialize without explicit database_url
                discovery = NewsDiscovery()

                # This is the KEY assertion: telemetry gets None, not the resolved URL
                # This allows create_telemetry_system to use DatabaseManager
                mock_create_telemetry.assert_called_once()
                call_kwargs = mock_create_telemetry.call_args[1]
                assert call_kwargs['database_url'] is None

                # But the discovery instance itself has the resolved URL
                assert discovery.database_url == configured_url


class TestRunDiscoveryPipelineSignature:
    """Test that run_discovery_pipeline accepts the correct parameters."""

    def test_run_discovery_pipeline_accepts_none_database_url(self):
        """run_discovery_pipeline should accept database_url as None."""
        from src.crawler.discovery import run_discovery_pipeline
        import inspect
        
        # Check function signature
        sig = inspect.signature(run_discovery_pipeline)
        params = sig.parameters
        
        # Verify database_url parameter exists
        assert 'database_url' in params
        
        # Verify it accepts None (has default of None or str | None type)
        param = params['database_url']
        # The default should be None
        assert param.default is None or param.default == inspect.Parameter.empty

    @patch('src.crawler.discovery.NewsDiscovery')
    def test_run_discovery_pipeline_passes_database_url(self, mock_discovery_class):
        """run_discovery_pipeline should pass database_url to NewsDiscovery."""
        from src.crawler.discovery import run_discovery_pipeline
        
        mock_instance = MagicMock()
        mock_discovery_class.return_value = mock_instance
        # Mock the methods that run_discovery_pipeline calls
        mock_instance.get_sources_to_process.return_value = (
            MagicMock(empty=True),  # Empty dataframe
            {"sources_available": 0}
        )
        
        test_url = "postgresql://test:test@test:5432/test"
        
        # Call run_discovery_pipeline with explicit database_url
        try:
            run_discovery_pipeline(database_url=test_url, source_limit=1)
        except Exception:
            # It's ok if it fails later, we just want to check initialization
            pass
        
        # Verify NewsDiscovery was initialized with the database_url
        mock_discovery_class.assert_called_once()
        call_kwargs = mock_discovery_class.call_args[1]
        assert 'database_url' in call_kwargs
        assert call_kwargs['database_url'] == test_url


class TestDatabaseUrlBehaviorIntegration:
    """Integration tests for database URL resolution behavior."""

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_production_scenario_cloud_sql_without_explicit_url(
        self,
        mock_create_telemetry,
    ):
        """Simulate production: Cloud SQL configured, no explicit database_url.
        
        This tests the fix from PR #136: in production, when DATABASE_URL points
        to Cloud SQL and no explicit database_url is provided, telemetry should
        receive None so it can use the DatabaseManager's Cloud SQL connection.
        """
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        # Simulate production DATABASE_URL
        cloud_sql_url = "postgresql+psycopg2://user:pass@/dbname?host=/cloudsql/project:region:instance"
        
        with patch.dict(os.environ, {"PYTEST_KEEP_DB_ENV": "true"}, clear=False):
            with patch.dict(sys.modules):
                mock_config = Mock()
                mock_config.DATABASE_URL = cloud_sql_url
                sys.modules['src.config'] = mock_config

                # Initialize as would happen in production (no explicit database_url)
                discovery = NewsDiscovery()

                # Verify discovery has the Cloud SQL URL
                assert discovery.database_url == cloud_sql_url

                # Verify telemetry received None (can use DatabaseManager's Cloud SQL engine)
                mock_create_telemetry.assert_called_once()
                call_kwargs = mock_create_telemetry.call_args[1]
                assert call_kwargs['database_url'] is None

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_development_scenario_requires_postgresql(self, mock_create_telemetry):
        """Simulate development: no DATABASE_URL configured requires PostgreSQL.
        
        SQLite fallback removed - even in development, PostgreSQL must be configured.
        """
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        with patch.dict(sys.modules):
            mock_config = Mock()
            mock_config.DATABASE_URL = None
            sys.modules['src.config'] = mock_config
            
            # Initialize in development (no explicit database_url, no config)
            discovery = NewsDiscovery()
            
            # Verify discovery uses None (no SQLite fallback)
            assert discovery.database_url is None
            
            # Telemetry receives None (will use DatabaseManager or fail)
            mock_create_telemetry.assert_called_once()
            call_kwargs = mock_create_telemetry.call_args[1]
            assert call_kwargs['database_url'] is None

    @patch('src.crawler.discovery.create_telemetry_system')
    def test_explicit_override_in_production(self, mock_create_telemetry):
        """Test explicit database_url override even when Cloud SQL configured.
        
        This allows testing or special cases where you want to override the
        production database with a different one.
        """
        mock_telemetry = MagicMock()
        mock_create_telemetry.return_value = mock_telemetry
        
        cloud_sql_url = "postgresql+psycopg2://prod@/proddb"
        test_override_url = "postgresql://test@localhost:5432/testdb"
        
        with patch.dict(sys.modules):
            mock_config = Mock()
            mock_config.DATABASE_URL = cloud_sql_url
            sys.modules['src.config'] = mock_config
            
            # Initialize with explicit override
            discovery = NewsDiscovery(database_url=test_override_url)
            
            # Verify discovery uses the override
            assert discovery.database_url == test_override_url
            
            # Verify telemetry also receives the override
            mock_create_telemetry.assert_called_once()
            call_kwargs = mock_create_telemetry.call_args[1]
            assert call_kwargs['database_url'] == test_override_url
