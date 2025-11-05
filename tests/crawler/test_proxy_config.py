"""Tests for proxy configuration and management."""

import os
from unittest import mock

import pytest

from src.crawler.proxy_config import (
    ProxyConfig,
    ProxyManager,
    ProxyProvider,
    get_proxy_manager,
    get_proxy_status,
    switch_proxy,
)


class TestProxyConfig:
    """Tests for ProxyConfig dataclass."""

    def test_initialization(self):
        """Test ProxyConfig initialization."""
        config = ProxyConfig(
            provider=ProxyProvider.ORIGIN,
            enabled=True,
            url="http://proxy.example.com:8080",
            username="user",
            password="pass",
        )

        assert config.provider == ProxyProvider.ORIGIN
        assert config.enabled is True
        assert config.url == "http://proxy.example.com:8080"
        assert config.username == "user"
        assert config.password == "pass"
        assert config.success_count == 0
        assert config.failure_count == 0
        assert config.avg_response_time == 0.0

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        config = ProxyConfig(provider=ProxyProvider.ORIGIN, enabled=True)

        # No requests yet
        assert config.success_rate == 0.0

        # All successful
        config.success_count = 10
        config.failure_count = 0
        assert config.success_rate == 100.0

        # Mixed
        config.success_count = 7
        config.failure_count = 3
        assert config.success_rate == 70.0

        # All failures
        config.success_count = 0
        config.failure_count = 10
        assert config.success_rate == 0.0

    def test_health_status(self):
        """Test health status categorization."""
        config = ProxyConfig(provider=ProxyProvider.ORIGIN, enabled=True)

        # Healthy (90%+)
        config.success_count = 95
        config.failure_count = 5
        assert config.health_status == "healthy"

        # Degraded (70-90%)
        config.success_count = 80
        config.failure_count = 20
        assert config.health_status == "degraded"

        # Unhealthy (50-70%)
        config.success_count = 60
        config.failure_count = 40
        assert config.health_status == "unhealthy"

        # Critical (<50%)
        config.success_count = 40
        config.failure_count = 60
        assert config.health_status == "critical"


class TestProxyManager:
    """Tests for ProxyManager class."""

    def test_initialization_with_defaults(self):
        """Test ProxyManager initializes with default environment."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            # Should have ORIGIN and DIRECT providers
            assert ProxyProvider.ORIGIN in manager.configs
            assert ProxyProvider.DIRECT in manager.configs

            # Default active provider should be ORIGIN
            assert manager.active_provider == ProxyProvider.ORIGIN

    def test_initialization_with_origin_env(self):
        """Test initialization with Origin proxy environment variables."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "origin",
                "ORIGIN_PROXY_URL": "http://custom.proxy:9999",
                "PROXY_USERNAME": "testuser",
                "PROXY_PASSWORD": "testpass",
            },
            clear=True,
        ):
            manager = ProxyManager()

            config = manager.configs[ProxyProvider.ORIGIN]
            assert config.enabled is True
            assert config.url == "http://custom.proxy:9999"
            assert config.username == "testuser"
            assert config.password == "testpass"

    def test_initialization_with_standard_proxy(self):
        """Test initialization with standard HTTP proxy."""
        with mock.patch.dict(
            os.environ,
            {
                "STANDARD_PROXY_URL": "http://standard.proxy:8080",
                "STANDARD_PROXY_USERNAME": "user",
                "STANDARD_PROXY_PASSWORD": "pass",
            },
            clear=True,
        ):
            manager = ProxyManager()

            assert ProxyProvider.STANDARD in manager.configs
            config = manager.configs[ProxyProvider.STANDARD]
            assert config.enabled is True
            assert config.url == "http://standard.proxy:8080"
            assert config.username == "user"

    def test_initialization_with_socks5_proxy(self):
        """Test initialization with SOCKS5 proxy."""
        with mock.patch.dict(
            os.environ,
            {
                "SOCKS5_PROXY_URL": "socks5://socks.proxy:1080",
            },
            clear=True,
        ):
            manager = ProxyManager()

            assert ProxyProvider.SOCKS5 in manager.configs
            config = manager.configs[ProxyProvider.SOCKS5]
            assert config.enabled is True
            assert config.url == "socks5://socks.proxy:1080"

    def test_initialization_with_scraper_api(self):
        """Test initialization with ScraperAPI."""
        with mock.patch.dict(
            os.environ,
            {
                "SCRAPERAPI_KEY": "test-api-key-123",
                "SCRAPERAPI_RENDER": "true",
                "SCRAPERAPI_COUNTRY": "uk",
            },
            clear=True,
        ):
            manager = ProxyManager()

            assert ProxyProvider.SCRAPER_API in manager.configs
            config = manager.configs[ProxyProvider.SCRAPER_API]
            assert config.enabled is True
            assert config.api_key == "test-api-key-123"
            assert config.options["render"] is True
            assert config.options["country"] == "uk"

    def test_initialization_with_brightdata(self):
        """Test initialization with BrightData."""
        with mock.patch.dict(
            os.environ,
            {
                "BRIGHTDATA_PROXY_URL": "http://bright.proxy:22225",
                "BRIGHTDATA_USERNAME": "customer-user",
                "BRIGHTDATA_PASSWORD": "password",
                "BRIGHTDATA_ZONE": "datacenter",
            },
            clear=True,
        ):
            manager = ProxyManager()

            assert ProxyProvider.BRIGHTDATA in manager.configs
            config = manager.configs[ProxyProvider.BRIGHTDATA]
            assert config.enabled is True
            assert config.url == "http://bright.proxy:22225"
            assert config.options["zone"] == "datacenter"

    def test_initialization_with_smartproxy(self):
        """Test initialization with Smartproxy."""
        with mock.patch.dict(
            os.environ,
            {
                "SMARTPROXY_URL": "http://smart.proxy:7000",
                "SMARTPROXY_USERNAME": "smart-user",
                "SMARTPROXY_PASSWORD": "smart-pass",
            },
            clear=True,
        ):
            manager = ProxyManager()

            assert ProxyProvider.SMARTPROXY in manager.configs
            config = manager.configs[ProxyProvider.SMARTPROXY]
            assert config.enabled is True

    def test_initialization_with_decodo_env_vars(self):
        """Test initialization with Decodo from environment variables."""
        with mock.patch.dict(
            os.environ,
            {
                "DECODO_USERNAME": "decodo-user",
                "DECODO_PASSWORD": "decodo-pass",
                "DECODO_HOST": "custom.decodo.com",
                "DECODO_COUNTRY": "ca",
                "DECODO_ROTATE_IP": "true",
            },
            clear=True,
        ):
            manager = ProxyManager()

            assert ProxyProvider.DECODO in manager.configs
            config = manager.configs[ProxyProvider.DECODO]
            assert config.enabled is True
            assert config.username == "decodo-user"
            assert config.password == "decodo-pass"
            assert config.options["host"] == "custom.decodo.com"
            assert config.options["country"] == "ca"
            assert config.options["rotate_ip"] is True

    def test_initialization_with_decodo_no_rotation(self):
        """Test initialization with Decodo without IP rotation."""
        with mock.patch.dict(
            os.environ,
            {
                "DECODO_USERNAME": "decodo-user",
                "DECODO_PASSWORD": "decodo-pass",
                "DECODO_ROTATE_IP": "false",
                "DECODO_PORT": "12345",
            },
            clear=True,
        ):
            manager = ProxyManager()

            config = manager.configs[ProxyProvider.DECODO]
            assert config.enabled is True
            assert config.options["rotate_ip"] is False
            assert config.options["port"] == "12345"

    def test_initialization_with_decodo_disabled(self):
        """Test that Decodo is disabled when no credentials."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            config = manager.configs[ProxyProvider.DECODO]
            assert config.enabled is False

    def test_active_provider_detection(self):
        """Test active provider detection from environment."""
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "direct"}, clear=True):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.DIRECT

    def test_active_provider_aliases(self):
        """Test provider name aliases."""
        # Test aliases that don't require configuration
        simple_test_cases = [
            ("none", ProxyProvider.DIRECT),
            ("off", ProxyProvider.DIRECT),
            ("disabled", ProxyProvider.DIRECT),
            ("origin", ProxyProvider.ORIGIN),
            ("default", ProxyProvider.ORIGIN),
        ]

        for alias, expected_provider in simple_test_cases:
            with mock.patch.dict(os.environ, {"PROXY_PROVIDER": alias}, clear=True):
                manager = ProxyManager()
                assert manager.active_provider == expected_provider

        # Test aliases that require provider configuration
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "http",
                "STANDARD_PROXY_URL": "http://test:8080",
            },
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.STANDARD

        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "https",
                "STANDARD_PROXY_URL": "http://test:8080",
            },
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.STANDARD

        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "socks",
                "SOCKS5_PROXY_URL": "socks5://test:1080",
            },
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.SOCKS5

        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "socks5",
                "SOCKS5_PROXY_URL": "socks5://test:1080",
            },
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.SOCKS5

    def test_active_provider_fallback_unknown(self):
        """Test fallback to ORIGIN for unknown provider."""
        with mock.patch.dict(
            os.environ, {"PROXY_PROVIDER": "unknown-provider"}, clear=True
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.ORIGIN

    def test_active_provider_fallback_unavailable(self):
        """Test fallback to ORIGIN if selected provider not configured."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "brightdata",
                # No BRIGHTDATA_PROXY_URL, so it won't be configured
            },
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.ORIGIN

    def test_get_active_config(self):
        """Test getting active configuration."""
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "direct"}, clear=True):
            manager = ProxyManager()
            config = manager.get_active_config()

            assert config.provider == ProxyProvider.DIRECT
            assert config.enabled is True

    def test_switch_provider_success(self):
        """Test switching to a different provider."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            # Switch from ORIGIN to DIRECT
            result = manager.switch_provider(ProxyProvider.DIRECT)

            assert result is True
            assert manager.active_provider == ProxyProvider.DIRECT

    def test_switch_provider_not_configured(self):
        """Test switching to unconfigured provider fails."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            # BRIGHTDATA not configured
            result = manager.switch_provider(ProxyProvider.BRIGHTDATA)

            assert result is False
            assert manager.active_provider == ProxyProvider.ORIGIN  # Unchanged

    def test_switch_provider_disabled(self):
        """Test switching to disabled provider fails."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            # DECODO is configured but disabled (no credentials)
            result = manager.switch_provider(ProxyProvider.DECODO)

            assert result is False

    def test_list_providers(self):
        """Test listing all providers with status."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            # Record some metrics
            manager.record_success(response_time=1.5)
            manager.record_failure()

            providers = manager.list_providers()

            assert "origin" in providers
            assert "direct" in providers
            assert providers["origin"]["enabled"] is True
            assert providers["origin"]["requests"] == 2

    def test_record_success(self):
        """Test recording successful requests."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            # Record success for active provider (ORIGIN)
            manager.record_success(response_time=1.2)
            manager.record_success(response_time=1.8)

            config = manager.configs[ProxyProvider.ORIGIN]
            assert config.success_count == 2
            assert config.failure_count == 0
            assert config.avg_response_time == 1.5  # Average of 1.2 and 1.8

    def test_record_success_specific_provider(self):
        """Test recording success for specific provider."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            manager.record_success(provider=ProxyProvider.DIRECT, response_time=0.5)

            config = manager.configs[ProxyProvider.DIRECT]
            assert config.success_count == 1
            assert config.avg_response_time == 0.5

    def test_record_failure(self):
        """Test recording failed requests."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            manager.record_failure()
            manager.record_failure()

            config = manager.configs[ProxyProvider.ORIGIN]
            assert config.failure_count == 2
            assert config.success_count == 0

    def test_record_failure_specific_provider(self):
        """Test recording failure for specific provider."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

            manager.record_failure(provider=ProxyProvider.DIRECT)

            config = manager.configs[ProxyProvider.DIRECT]
            assert config.failure_count == 1

    def test_get_requests_proxies_origin(self):
        """Test requests proxies for ORIGIN provider (returns None)."""
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "origin"}, clear=True):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()

            # Origin uses custom adapter, not requests proxies
            assert proxies is None

    def test_get_requests_proxies_direct(self):
        """Test requests proxies for DIRECT provider (returns None)."""
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "direct"}, clear=True):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()

            assert proxies is None

    def test_get_requests_proxies_standard(self):
        """Test requests proxies for standard HTTP proxy."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "standard",
                "STANDARD_PROXY_URL": "http://proxy.example.com:8080",
                "STANDARD_PROXY_USERNAME": "user",
                "STANDARD_PROXY_PASSWORD": "pass",
            },
            clear=True,
        ):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()

            assert proxies is not None
            assert "http" in proxies
            assert "https" in proxies
            assert "user:pass@" in proxies["http"]

    def test_get_requests_proxies_without_auth(self):
        """Test requests proxies without authentication."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "socks5",
                "SOCKS5_PROXY_URL": "socks5://proxy.example.com:1080",
            },
            clear=True,
        ):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()

            assert proxies is not None
            assert proxies["http"] == "socks5://proxy.example.com:1080"

    def test_get_requests_proxies_decodo_rotation(self):
        """Test requests proxies for Decodo with rotation."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "decodo",
                "DECODO_USERNAME": "user",
                "DECODO_PASSWORD": "pass",
                "DECODO_ROTATE_IP": "true",
            },
            clear=True,
        ):
            manager = ProxyManager()

            # Mock random to get consistent port - Decodo uses ports 10001-10010 for rotation
            import random

            with mock.patch.object(random, "randint", return_value=10005):
                proxies = manager.get_requests_proxies()

            assert proxies is not None
            assert "10005" in proxies["http"]  # Rotated port

    def test_get_rotating_decodo_url(self):
        """Test Decodo rotating URL generation."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "decodo",  # Set active provider
                "DECODO_USERNAME": "user",
                "DECODO_PASSWORD": "pass",
                "DECODO_HOST": "test.decodo.com",
                "DECODO_ROTATE_IP": "true",
            },
            clear=True,
        ):
            manager = ProxyManager()

            # Mock random to get consistent port - Decodo uses ports 10001-10010 for rotation
            import random

            with mock.patch.object(random, "randint", return_value=10007):
                url = manager.get_rotating_decodo_url()

            assert url is not None
            assert "user:pass@" in url
            assert "test.decodo.com" in url
            assert ":10007" in url

    def test_get_rotating_decodo_url_non_decodo_provider(self):
        """Test rotating URL returns None for non-Decodo provider."""
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "origin"}, clear=True):
            manager = ProxyManager()
            url = manager.get_rotating_decodo_url()

            assert url is None

    def test_get_rotating_decodo_url_rotation_disabled(self):
        """Test rotating URL returns static URL when rotation disabled."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "decodo",
                "DECODO_USERNAME": "user",
                "DECODO_PASSWORD": "pass",
                "DECODO_ROTATE_IP": "false",
                "DECODO_PORT": "10000",
            },
            clear=True,
        ):
            manager = ProxyManager()
            url = manager.get_rotating_decodo_url()

            # Should return static URL from config
            assert url is not None
            assert ":10000" in url

    def test_get_rotating_decodo_url_missing_credentials(self):
        """Test rotating URL returns None when credentials missing."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "decodo",
                # No credentials
                "DECODO_ROTATE_IP": "true",
            },
            clear=True,
        ):
            manager = ProxyManager()
            url = manager.get_rotating_decodo_url()

            assert url is None

    def test_should_use_origin_proxy(self):
        """Test checking if origin proxy should be used."""
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "origin"}, clear=True):
            manager = ProxyManager()
            assert manager.should_use_origin_proxy() is True

        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "direct"}, clear=True):
            manager = ProxyManager()
            assert manager.should_use_origin_proxy() is False

    def test_get_origin_proxy_url(self):
        """Test getting origin proxy URL."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "origin",
                "ORIGIN_PROXY_URL": "http://custom.origin:9999",
            },
            clear=True,
        ):
            manager = ProxyManager()
            url = manager.get_origin_proxy_url()

            assert url == "http://custom.origin:9999"

    def test_get_origin_proxy_url_non_origin_provider(self):
        """Test getting origin URL returns None for non-origin provider."""
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "direct"}, clear=True):
            manager = ProxyManager()
            url = manager.get_origin_proxy_url()

            assert url is None


class TestGlobalFunctions:
    """Tests for global proxy management functions."""

    def test_get_proxy_manager_singleton(self):
        """Test that get_proxy_manager returns same instance."""
        # Reset global
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None

        with mock.patch.dict(os.environ, {}, clear=True):
            manager1 = get_proxy_manager()
            manager2 = get_proxy_manager()

            assert manager1 is manager2

    def test_switch_proxy_function(self):
        """Test switch_proxy global function."""
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None

        with mock.patch.dict(os.environ, {}, clear=True):
            result = switch_proxy("direct")

            assert result is True
            manager = get_proxy_manager()
            assert manager.active_provider == ProxyProvider.DIRECT

    def test_switch_proxy_function_unknown(self):
        """Test switch_proxy with unknown provider."""
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None

        with mock.patch.dict(os.environ, {}, clear=True):
            result = switch_proxy("unknown-provider")

            assert result is False

    def test_get_proxy_status(self):
        """Test get_proxy_status function."""
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None

        with mock.patch.dict(os.environ, {}, clear=True):
            status = get_proxy_status()

            assert "active" in status
            assert "providers" in status
            assert status["active"] == "origin"
            assert "origin" in status["providers"]
            assert "direct" in status["providers"]
