"""Tests for Squid-first proxy configuration."""

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
    """Validate the ProxyConfig dataclass."""

    def test_initialization(self):
        config = ProxyConfig(
            provider=ProxyProvider.SQUID,
            enabled=True,
            url="http://squid.local:3128",
            username="user",
            password="pass",
        )

        assert config.provider == ProxyProvider.SQUID
        assert config.enabled is True
        assert config.url == "http://squid.local:3128"
        assert config.username == "user"
        assert config.password == "pass"
        assert config.success_count == 0
        assert config.failure_count == 0
        assert config.avg_response_time == 0.0

    def test_success_rate_and_health(self):
        config = ProxyConfig(provider=ProxyProvider.SQUID, enabled=True)

        assert config.success_rate == 0.0
        assert config.health_status == "critical"

        config.success_count = 9
        config.failure_count = 1
        assert config.success_rate == 90.0
        assert config.health_status == "healthy"

        config.success_count = 7
        config.failure_count = 3
        assert config.success_rate == 70.0
        assert config.health_status == "degraded"

        config.success_count = 6
        config.failure_count = 4
        assert config.health_status == "unhealthy"

        config.success_count = 4
        config.failure_count = 6
        assert config.health_status == "critical"


class TestProxyManager:
    """Ensure ProxyManager only exposes Squid and modern providers."""

    def test_initialization_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

        assert ProxyProvider.SQUID in manager.configs
        assert ProxyProvider.DIRECT in manager.configs
        assert manager.active_provider == ProxyProvider.SQUID
        squid_config = manager.configs[ProxyProvider.SQUID]
        assert squid_config.enabled is True
        assert squid_config.url.startswith("http")

    def test_initialization_with_standard_proxy(self):
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

        config = manager.configs[ProxyProvider.STANDARD]
        assert config.enabled is True
        assert config.url == "http://standard.proxy:8080"
        assert config.username == "user"

    def test_initialization_with_socks5_proxy(self):
        with mock.patch.dict(
            os.environ,
            {
                "SOCKS5_PROXY_URL": "socks5://socks.proxy:1080",
            },
            clear=True,
        ):
            manager = ProxyManager()

        config = manager.configs[ProxyProvider.SOCKS5]
        assert config.enabled is True
        assert config.url == "socks5://socks.proxy:1080"

    def test_initialization_with_scraper_api(self):
        with mock.patch.dict(
            os.environ,
            {
                "SCRAPERAPI_KEY": "test-api-key",
                "SCRAPERAPI_RENDER": "true",
                "SCRAPERAPI_COUNTRY": "ca",
            },
            clear=True,
        ):
            manager = ProxyManager()

        config = manager.configs[ProxyProvider.SCRAPER_API]
        assert config.enabled is True
        assert config.api_key == "test-api-key"
        assert config.options["render"] is True
        assert config.options["country"] == "ca"

    def test_initialization_with_brightdata(self):
        with mock.patch.dict(
            os.environ,
            {
                "BRIGHTDATA_PROXY_URL": "http://bright.proxy:22225",
                "BRIGHTDATA_USERNAME": "customer",
                "BRIGHTDATA_PASSWORD": "secret",
                "BRIGHTDATA_ZONE": "residential",
            },
            clear=True,
        ):
            manager = ProxyManager()

        config = manager.configs[ProxyProvider.BRIGHTDATA]
        assert config.enabled is True
        assert config.url == "http://bright.proxy:22225"
        assert config.options["zone"] == "residential"

    def test_initialization_with_smartproxy(self):
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

        config = manager.configs[ProxyProvider.SMARTPROXY]
        assert config.enabled is True
        assert config.url == "http://smart.proxy:7000"

    def test_active_provider_aliases(self):
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "default"}, clear=True):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.SQUID

        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "off"}, clear=True):
            manager = ProxyManager()
            # In production, 'off' is forced to SQUID to prevent unproxied traffic
            assert manager.active_provider == ProxyProvider.SQUID

        with mock.patch.dict(
            os.environ,
            {"PROXY_PROVIDER": "http", "STANDARD_PROXY_URL": "http://test:8080"},
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.STANDARD

    def test_active_provider_fallbacks(self):
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "unknown"}, clear=True):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.SQUID

        with mock.patch.dict(
            os.environ,
            {"PROXY_PROVIDER": "standard"},
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.SQUID

    def test_switch_provider(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

        assert manager.active_provider == ProxyProvider.SQUID
        assert manager.switch_provider(ProxyProvider.DIRECT) is True
        assert manager.active_provider == ProxyProvider.DIRECT

    def test_switch_provider_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

        assert manager.switch_provider(ProxyProvider.BRIGHTDATA) is False
        assert manager.active_provider == ProxyProvider.SQUID

    def test_list_providers(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()
            manager.record_success(response_time=1.0)
            manager.record_failure()

        providers = manager.list_providers()
        assert "squid" in providers
        assert providers["squid"]["enabled"] is True
        assert providers["squid"]["requests"] == 2

    def test_record_success_and_failure(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

        manager.record_success(response_time=1.0)
        manager.record_success(provider=ProxyProvider.DIRECT, response_time=0.5)
        manager.record_failure()

        squid = manager.configs[ProxyProvider.SQUID]
        direct = manager.configs[ProxyProvider.DIRECT]
        assert squid.success_count == 1
        assert direct.success_count == 1
        assert squid.failure_count == 1

    def test_get_requests_proxies(self):
        # In production, 'direct' is forced to SQUID to prevent unproxied traffic
        with mock.patch.dict(os.environ, {"PROXY_PROVIDER": "direct"}, clear=True):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()
            assert proxies is not None
            assert "http" in proxies
            assert "https" in proxies

        # Squid proxy without authentication
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "squid",
                "SQUID_PROXY_URL": "http://squid.example:3128",
            },
            clear=True,
        ):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()
            assert proxies["http"] == "http://squid.example:3128"
            assert proxies["https"] == "http://squid.example:3128"

        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "standard",
                "STANDARD_PROXY_URL": "http://proxy.example.com:8080",
            },
            clear=True,
        ):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()
            assert proxies["http"] == "http://proxy.example.com:8080"


class TestGlobalFunctions:
    """Test helper functions that wrap ProxyManager."""

    def test_get_proxy_manager_singleton(self):
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None
        with mock.patch.dict(os.environ, {}, clear=True):
            mgr1 = get_proxy_manager()
            mgr2 = get_proxy_manager()

        assert mgr1 is mgr2

    def test_switch_proxy_function(self):
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None
        with mock.patch.dict(os.environ, {}, clear=True):
            assert switch_proxy("direct") is True
            assert get_proxy_manager().active_provider == ProxyProvider.DIRECT

    def test_switch_proxy_unknown_provider(self):
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None
        with mock.patch.dict(os.environ, {}, clear=True):
            assert switch_proxy("unknown") is False

    def test_get_proxy_status(self):
        import src.crawler.proxy_config as pc

        pc._proxy_manager = None
        with mock.patch.dict(os.environ, {}, clear=True):
            status = get_proxy_status()

        assert status["active"] == "squid"
        assert "squid" in status["providers"]
        assert "direct" in status["providers"]


class TestProxyConfigEdgeCases:
    """Test edge cases and error handling in proxy configuration."""

    def test_success_rate_with_zero_requests(self):
        """Success rate should be 0.0 when no requests made."""
        config = ProxyConfig(provider=ProxyProvider.SQUID, enabled=True)
        assert config.success_rate == 0.0

    def test_health_status_boundaries(self):
        """Test health status transitions at exact boundaries."""
        config = ProxyConfig(provider=ProxyProvider.SQUID, enabled=True)

        # Exactly 90% - should be healthy
        config.success_count = 90
        config.failure_count = 10
        assert config.success_rate == 90.0
        assert config.health_status == "healthy"

        # Exactly 70% - should be degraded
        config.success_count = 70
        config.failure_count = 30
        assert config.success_rate == 70.0
        assert config.health_status == "degraded"

        # Exactly 50% - should be unhealthy
        config.success_count = 50
        config.failure_count = 50
        assert config.success_rate == 50.0
        assert config.health_status == "unhealthy"

    def test_switch_provider_to_disabled_provider(self):
        """Cannot switch to a disabled provider."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

        # BRIGHTDATA not configured/enabled
        result = manager.switch_provider(ProxyProvider.BRIGHTDATA)
        assert result is False
        assert manager.active_provider == ProxyProvider.SQUID

    def test_record_success_updates_avg_response_time(self):
        """Response time average should update correctly."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

        config = manager.configs[ProxyProvider.SQUID]

        # First request: 1.0s
        manager.record_success(response_time=1.0)
        assert config.avg_response_time == 1.0

        # Second request: 2.0s, average should be 1.5s
        manager.record_success(response_time=2.0)
        assert abs(config.avg_response_time - 1.5) < 0.01

    def test_get_requests_proxies_with_auth_injection(self):
        """Proxy URLs with username/password should have auth injected."""
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

        assert proxies["http"] == "http://user:pass@proxy.example.com:8080"
        assert proxies["https"] == "http://user:pass@proxy.example.com:8080"

    def test_get_requests_proxies_with_username_no_password(self):
        """Auth injection should work with only username."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "standard",
                "STANDARD_PROXY_URL": "http://proxy.example.com:8080",
                "STANDARD_PROXY_USERNAME": "user",
            },
            clear=True,
        ):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()

        # Should inject username with empty password
        assert "user:@proxy.example.com" in proxies["http"]

    def test_get_requests_proxies_url_without_protocol(self):
        """URLs without protocol should get http:// added."""
        with mock.patch.dict(
            os.environ,
            {
                "PROXY_PROVIDER": "standard",
                "STANDARD_PROXY_URL": "proxy.example.com:8080",
                "STANDARD_PROXY_USERNAME": "user",
                "STANDARD_PROXY_PASSWORD": "pass",
            },
            clear=True,
        ):
            manager = ProxyManager()
            proxies = manager.get_requests_proxies()

        assert proxies["http"] == "http://user:pass@proxy.example.com:8080"

    def test_active_provider_with_explicit_enum_value(self):
        """PROXY_PROVIDER can be set to enum value directly."""
        with mock.patch.dict(
            os.environ,
            {"PROXY_PROVIDER": "squid"},
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.SQUID

    def test_active_provider_case_insensitive(self):
        """PROXY_PROVIDER should be case insensitive."""
        with mock.patch.dict(
            os.environ,
            {"PROXY_PROVIDER": "SQUID"},
            clear=True,
        ):
            manager = ProxyManager()
            assert manager.active_provider == ProxyProvider.SQUID

    def test_list_providers_shows_all_metrics(self):
        """list_providers should return all expected fields."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()
            manager.record_success(response_time=1.5)
            manager.record_failure()

        providers = manager.list_providers()
        squid_info = providers["squid"]

        assert "enabled" in squid_info
        assert "url" in squid_info
        assert "health" in squid_info
        assert "success_rate" in squid_info
        assert "requests" in squid_info
        assert "avg_response_time" in squid_info

        assert squid_info["requests"] == 2
        assert squid_info["success_rate"] == "50.0%"

    def test_record_failure_for_specific_provider(self):
        """Can record failure for non-active provider."""
        with mock.patch.dict(os.environ, {}, clear=True):
            manager = ProxyManager()

        manager.record_failure(provider=ProxyProvider.DIRECT)
        direct_config = manager.configs[ProxyProvider.DIRECT]
        squid_config = manager.configs[ProxyProvider.SQUID]

        assert direct_config.failure_count == 1
        assert squid_config.failure_count == 0
