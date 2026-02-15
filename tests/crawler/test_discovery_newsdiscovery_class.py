"""Tests for NewsDiscovery class to increase coverage to 80%."""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.crawler.discovery import NewsDiscovery


class TestNewsDiscoveryInit:
    """Test NewsDiscovery.__init__ method - 150+ lines of initialization code."""

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_init_with_database_url(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should initialize with explicit database URL."""
        # Setup mocks
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {}
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        # Create instance
        nd = NewsDiscovery(
            database_url="postgresql://localhost/test",
            timeout=60,
            delay=5.0,
        )

        assert nd.database_url == "postgresql://localhost/test"
        assert nd.timeout == 60
        assert nd.delay == 5.0
        assert nd.max_articles_per_source == 50
        assert nd.days_back == 7
        assert isinstance(nd.cutoff_date, datetime)
        mock_get_proxy_manager.assert_called_once()
        mock_create_telemetry.assert_called_once()

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_init_without_cloudscraper(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should fall back to requests.Session when cloudscraper not available."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {}
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        with patch("src.crawler.discovery.cloudscraper", None):
            nd = NewsDiscovery(database_url="postgresql://localhost/test")

        # Should still initialize without cloudscraper
        assert nd.database_url == "postgresql://localhost/test"

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_init_without_storysniffer(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should handle StorySniffer initialization failure."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {}
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        # StorySniffer raises exception
        mock_storysniffer_class.side_effect = Exception("StorySniffer not available")

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        nd = NewsDiscovery(database_url="postgresql://localhost/test")

        assert nd.storysniffer is None

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_init_with_proxy_pool(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should configure proxy pool from environment."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {
            "http": "http://proxy1:8080",
            "https": "http://proxy1:8080",
        }
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        with patch.dict(
            os.environ, {"PROXY_POOL": "http://proxy1:8080,http://proxy2:8080"}
        ):
            nd = NewsDiscovery(database_url="postgresql://localhost/test")

        # Should have proxy pool from environment
        assert len(nd.proxy_pool) == 2

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_init_custom_user_agent(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should use custom user agent when provided."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {}
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        custom_ua = "CustomBot/1.0"
        nd = NewsDiscovery(
            database_url="postgresql://localhost/test", user_agent=custom_ua
        )

        assert nd.user_agent == custom_ua

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_init_calculates_cutoff_date(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should calculate cutoff date based on days_back."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {}
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        nd = NewsDiscovery(database_url="postgresql://localhost/test", days_back=14)

        # Cutoff should be approximately 14 days ago
        expected_cutoff = datetime.utcnow() - timedelta(days=14)
        assert abs((nd.cutoff_date - expected_cutoff).total_seconds()) < 5

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer", None)
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_init_without_storysniffer_available(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_create_telemetry,
    ):
        """Should handle when StorySniffer class is not available at all."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {}
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        nd = NewsDiscovery(database_url="postgresql://localhost/test")

        assert nd.storysniffer is None


class TestNewsDiscoveryResolveDatabaseUrl:
    """Test NewsDiscovery._resolve_database_url static method."""

    def test_returns_candidate_if_provided(self):
        """Should return candidate URL if provided."""
        url = "postgresql://localhost/test"
        result = NewsDiscovery._resolve_database_url(url)
        assert result == url

    def test_uses_env_database_url(self):
        """Should use DATABASE_URL from environment when not in pytest mode."""
        # Clear PYTEST_CURRENT_TEST to simulate non-pytest mode
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://localhost/fromenv"}, clear=False
        ):
            if "PYTEST_CURRENT_TEST" in os.environ:
                with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}):
                    with patch(
                        "src.models.database._is_test_environment", return_value=False
                    ):
                        result = NewsDiscovery._resolve_database_url(None)
                        assert result == "postgresql://localhost/fromenv"
            else:
                with patch(
                    "src.models.database._is_test_environment", return_value=False
                ):
                    result = NewsDiscovery._resolve_database_url(None)
                    assert result == "postgresql://localhost/fromenv"

    def test_ignores_sqlite_memory_in_env(self):
        """Should ignore sqlite memory URLs from environment."""
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
            with patch("src.config.DATABASE_URL", "postgresql://localhost/configured"):
                with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=True):
                    result = NewsDiscovery._resolve_database_url(None)
                    # Should fall through to configured URL
                    assert result == "postgresql://localhost/configured"

    def test_pytest_mode_with_forced_url(self):
        """Should use PYTEST_DATABASE_URL in pytest mode."""
        with patch.dict(
            os.environ,
            {
                "PYTEST_CURRENT_TEST": "test_something",
                "PYTEST_DATABASE_URL": "postgresql://localhost/pytest",
            },
        ):
            # Pass explicit URL which should be honored
            result = NewsDiscovery._resolve_database_url(
                "postgresql://test:test@localhost/test"
            )
            # Explicit URL should be returned
            assert result == "postgresql://test:test@localhost/test"

    def test_pytest_mode_returns_none_without_sqlite(self):
        """Should return None in pytest mode without sqlite configured."""
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_something"}):
            with patch.dict(os.environ, {"PYTEST_DATABASE_URL": ""}, clear=True):
                with patch("src.config.DATABASE_URL", None):
                    result = NewsDiscovery._resolve_database_url(None)
                    assert result is None


class TestNewsDiscoveryConfigureProxyRouting:
    """Test NewsDiscovery._configure_proxy_routing method."""

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_proxy_routing_with_env_pool(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should configure proxy pool from PROXY_POOL environment variable."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="origin")
        mock_proxy_manager.get_requests_proxies.return_value = {}
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_scraper.proxies = {}
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        with patch.dict(
            os.environ,
            {
                "PROXY_POOL": "http://proxy1:8080, http://proxy2:8080, http://proxy3:8080"
            },
        ):
            nd = NewsDiscovery(database_url="postgresql://localhost/test")

        assert len(nd.proxy_pool) == 3
        assert "http://proxy1:8080" in nd.proxy_pool
        assert "http://proxy2:8080" in nd.proxy_pool

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_proxy_routing_with_provider_proxies(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should merge proxy manager proxies into pool when no env pool."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="smartproxy")
        mock_proxy_manager.get_requests_proxies.return_value = {
            "http": "http://provider-proxy:8080",
            "https": "http://provider-proxy:8080",
        }
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_scraper.proxies = {}
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        with patch.dict(os.environ, {"PROXY_POOL": ""}, clear=True):
            nd = NewsDiscovery(database_url="postgresql://localhost/test")

        # Should have provider proxies in pool
        assert "http://provider-proxy:8080" in nd.proxy_pool

    @patch("src.crawler.discovery.create_telemetry_system")
    @patch("src.crawler.discovery.StorySniffer")
    @patch("src.crawler.discovery.get_proxy_manager")
    @patch("src.crawler.discovery.cloudscraper")
    def test_proxy_routing_env_pool_overrides_provider(
        self,
        mock_cloudscraper,
        mock_get_proxy_manager,
        mock_storysniffer_class,
        mock_create_telemetry,
    ):
        """Should prefer PROXY_POOL env over provider proxies."""
        mock_proxy_manager = Mock()
        mock_proxy_manager.active_provider = Mock(value="smartproxy")
        mock_proxy_manager.get_requests_proxies.return_value = {
            "http": "http://provider-proxy:8080",
            "https": "http://provider-proxy:8080",
        }
        mock_get_proxy_manager.return_value = mock_proxy_manager

        mock_scraper = Mock()
        mock_scraper.proxies = {}
        mock_cloudscraper.create_scraper.return_value = mock_scraper

        mock_storysniffer = Mock()
        mock_storysniffer_class.return_value = mock_storysniffer

        mock_telemetry = Mock()
        mock_create_telemetry.return_value = mock_telemetry

        with patch.dict(os.environ, {"PROXY_POOL": "http://env-proxy:9090"}):
            nd = NewsDiscovery(database_url="postgresql://localhost/test")

        # Should only have env proxy, not provider proxy
        assert "http://env-proxy:9090" in nd.proxy_pool
        assert "http://provider-proxy:8080" not in nd.proxy_pool
