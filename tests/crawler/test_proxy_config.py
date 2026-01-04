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
