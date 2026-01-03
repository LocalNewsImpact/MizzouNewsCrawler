"""Proxy configuration with multiple provider support and master switch."""

import logging
import os
import warnings
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.crawler.utils import mask_proxy_url

# Suppress InsecureRequestWarning for proxy connections (expected behavior)
try:
    from urllib3.exceptions import InsecureRequestWarning

    warnings.filterwarnings("ignore", category=InsecureRequestWarning)
except ImportError:
    # If urllib3 is not available, we can't suppress InsecureRequestWarning.
    # This is fine; continue without suppressing the warning.
    pass

logger = logging.getLogger(__name__)


class ProxyProvider(Enum):
    """Available proxy providers."""

    # Direct connection (no proxy)
    DIRECT = "direct"

    # Standard HTTP/HTTPS proxy
    STANDARD = "standard"

    # SOCKS5 proxy
    SOCKS5 = "socks5"

    # Rotating proxy service
    ROTATING = "rotating"

    # ScraperAPI or similar services
    SCRAPER_API = "scraper_api"

    # BrightData (Luminati) proxy
    BRIGHTDATA = "brightdata"

    # Squid residential proxy (default)
    SQUID = "squid"

    # Smartproxy
    SMARTPROXY = "smartproxy"


@dataclass
class ProxyConfig:
    """Configuration for a proxy provider."""

    provider: ProxyProvider
    enabled: bool
    url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None

    # Provider-specific options
    options: Optional[dict] = None

    # Performance tracking
    success_count: int = 0
    failure_count: int = 0
    avg_response_time: float = 0.0

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return (self.success_count / total) * 100

    @property
    def health_status(self) -> str:
        """Get health status based on success rate."""
        rate = self.success_rate
        if rate >= 90:
            return "healthy"
        elif rate >= 70:
            return "degraded"
        elif rate >= 50:
            return "unhealthy"
        else:
            return "critical"


class ProxyManager:
    """Manages multiple proxy providers with master switch control."""

    def __init__(self):
        """Initialize proxy manager from environment variables."""
        self.configs = {}
        self._load_configurations()
        self._active_provider = self._get_active_provider()

    @property
    def active_provider(self) -> ProxyProvider:
        """Get the currently active proxy provider."""
        return self._active_provider

    def _load_configurations(self):
        """Load all proxy configurations from environment."""

        # Direct connection (no proxy)
        self.configs[ProxyProvider.DIRECT] = ProxyConfig(
            provider=ProxyProvider.DIRECT,
            enabled=True,  # Always available
        )

        # Squid residential proxy (default provider)
        squid_url = os.getenv("SQUID_PROXY_URL", "http://t9880447.eero.online:3128")
        self.configs[ProxyProvider.SQUID] = ProxyConfig(
            provider=ProxyProvider.SQUID,
            enabled=bool(squid_url),
            url=squid_url,
            username=os.getenv("SQUID_PROXY_USERNAME"),
            password=os.getenv("SQUID_PROXY_PASSWORD"),
        )

        # Standard HTTP proxy
        standard_url = os.getenv("STANDARD_PROXY_URL")
        if standard_url:
            self.configs[ProxyProvider.STANDARD] = ProxyConfig(
                provider=ProxyProvider.STANDARD,
                enabled=bool(standard_url),
                url=standard_url,
                username=os.getenv("STANDARD_PROXY_USERNAME"),
                password=os.getenv("STANDARD_PROXY_PASSWORD"),
            )

        # SOCKS5 proxy
        socks_url = os.getenv("SOCKS5_PROXY_URL")
        if socks_url:
            self.configs[ProxyProvider.SOCKS5] = ProxyConfig(
                provider=ProxyProvider.SOCKS5,
                enabled=bool(socks_url),
                url=socks_url,
                username=os.getenv("SOCKS5_PROXY_USERNAME"),
                password=os.getenv("SOCKS5_PROXY_PASSWORD"),
            )

        # ScraperAPI
        scraper_api_key = os.getenv("SCRAPERAPI_KEY")
        if scraper_api_key:
            self.configs[ProxyProvider.SCRAPER_API] = ProxyConfig(
                provider=ProxyProvider.SCRAPER_API,
                enabled=bool(scraper_api_key),
                url="http://api.scraperapi.com",
                api_key=scraper_api_key,
                options={
                    "render": os.getenv("SCRAPERAPI_RENDER", "false").lower() == "true",
                    "country": os.getenv("SCRAPERAPI_COUNTRY", "us"),
                },
            )

        # BrightData (Luminati)
        brightdata_url = os.getenv("BRIGHTDATA_PROXY_URL")
        if brightdata_url:
            self.configs[ProxyProvider.BRIGHTDATA] = ProxyConfig(
                provider=ProxyProvider.BRIGHTDATA,
                enabled=bool(brightdata_url),
                url=brightdata_url,
                username=os.getenv("BRIGHTDATA_USERNAME"),
                password=os.getenv("BRIGHTDATA_PASSWORD"),
                options={
                    "zone": os.getenv("BRIGHTDATA_ZONE", "residential"),
                },
            )

        # Smartproxy
        smartproxy_url = os.getenv("SMARTPROXY_URL")
        if smartproxy_url:
            self.configs[ProxyProvider.SMARTPROXY] = ProxyConfig(
                provider=ProxyProvider.SMARTPROXY,
                enabled=bool(smartproxy_url),
                url=smartproxy_url,
                username=os.getenv("SMARTPROXY_USERNAME"),
                password=os.getenv("SMARTPROXY_PASSWORD"),
            )

    def _get_active_provider(self) -> ProxyProvider:
        """Determine active provider from PROXY_PROVIDER env var."""
        provider_name = os.getenv("PROXY_PROVIDER", "squid").lower()

        # Map common aliases
        aliases = {
            "none": ProxyProvider.DIRECT,
            "off": ProxyProvider.DIRECT,
            "disabled": ProxyProvider.DIRECT,
            "default": ProxyProvider.SQUID,
            "standard": ProxyProvider.STANDARD,
            "http": ProxyProvider.STANDARD,
            "https": ProxyProvider.STANDARD,
            "socks": ProxyProvider.SOCKS5,
            "socks5": ProxyProvider.SOCKS5,
            "scraper": ProxyProvider.SCRAPER_API,
            "scraperapi": ProxyProvider.SCRAPER_API,
            "brightdata": ProxyProvider.BRIGHTDATA,
            "luminati": ProxyProvider.BRIGHTDATA,
            "smartproxy": ProxyProvider.SMARTPROXY,
            "squid": ProxyProvider.SQUID,
        }

        provider = aliases.get(provider_name)
        if provider is None:
            try:
                provider = ProxyProvider(provider_name)
            except ValueError:
                logger.warning(
                    f"Unknown proxy provider '{provider_name}', falling back to SQUID"
                )
                provider = ProxyProvider.SQUID

        # Verify provider is available
        if provider not in self.configs or not self.configs[provider].enabled:
            fallback_provider = (
                ProxyProvider.SQUID
                if self.configs.get(ProxyProvider.SQUID)
                and self.configs[ProxyProvider.SQUID].enabled
                else ProxyProvider.DIRECT
            )
            logger.warning(
                f"Provider {provider.value if provider else provider_name} not configured, "
                f"falling back to {fallback_provider.value}"
            )
            provider = fallback_provider

        logger.info(f"🔀 Active proxy provider: {provider.value}")
        return provider

    def get_active_config(self) -> ProxyConfig:
        """Get configuration for currently active provider."""
        return self.configs[self._active_provider]

    def switch_provider(self, provider: ProxyProvider) -> bool:
        """
        Switch to a different proxy provider.

        Returns:
            bool: True if switch successful, False if provider unavailable
        """
        if provider not in self.configs:
            logger.error(f"Provider {provider.value} not configured")
            return False

        if not self.configs[provider].enabled:
            logger.error(f"Provider {provider.value} not enabled")
            return False

        old_provider = self._active_provider
        self._active_provider = provider

        logger.info(f"🔄 Switched proxy: {old_provider.value} → {provider.value}")
        return True

    def list_providers(self) -> dict:
        """List all available providers with their status."""
        return {
            provider.value: {
                "enabled": config.enabled,
                "url": mask_proxy_url(config.url) or "N/A",
                "health": config.health_status,
                "success_rate": f"{config.success_rate:.1f}%",
                "requests": config.success_count + config.failure_count,
                "avg_response_time": f"{config.avg_response_time:.2f}s",
            }
            for provider, config in self.configs.items()
        }

    def record_success(
        self, provider: Optional[ProxyProvider] = None, response_time: float = 0.0
    ):
        """Record a successful request."""
        provider = provider or self._active_provider
        if provider in self.configs:
            config = self.configs[provider]
            config.success_count += 1

            # Update rolling average response time
            total = config.success_count + config.failure_count
            config.avg_response_time = (
                config.avg_response_time * (total - 1) + response_time
            ) / total

    def record_failure(self, provider: Optional[ProxyProvider] = None):
        """Record a failed request."""
        provider = provider or self._active_provider
        if provider in self.configs:
            self.configs[provider].failure_count += 1

    def get_requests_proxies(self) -> Optional[dict]:
        """Return proxy configuration formatted for the requests library.

        For Squid (the default provider) this returns the configured HTTP(S)
        proxy mapping with credentials injected when provided. Direct mode
        returns ``None`` so callers fall back to raw network access.
        """
        config = self.get_active_config()

        # Direct connection uses no proxy
        if config.provider == ProxyProvider.DIRECT:
            return None

        # Build proxy URL with auth for other providers
        if config.url:
            if config.username:
                auth = f"{config.username}:{config.password or ''}@"
                # Insert auth into URL after protocol
                if "://" in config.url:
                    protocol, rest = config.url.split("://", 1)
                    proxy_url = f"{protocol}://{auth}{rest}"
                else:
                    proxy_url = f"http://{auth}{config.url}"
            else:
                proxy_url = config.url

            # Return proxies dict for requests
            return {
                "http": proxy_url,
                "https": proxy_url,
            }

        return None


# Global proxy manager instance
_proxy_manager: Optional[ProxyManager] = None


def get_proxy_manager() -> ProxyManager:
    """Get or create global proxy manager instance."""
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager()
    return _proxy_manager


def switch_proxy(provider: str) -> bool:
    """
    Master switch function to change proxy provider.

    Args:
        provider: Name of provider (origin, direct, standard, brightdata, etc.)

    Returns:
        bool: True if switch successful

    Example:
        >>> switch_proxy("direct")  # Disable proxy
        >>> switch_proxy("brightdata")  # Switch to BrightData
        >>> switch_proxy("origin")  # Back to default
    """
    manager = get_proxy_manager()

    # Try to match provider name
    provider_lower = provider.lower()
    for proxy_provider in ProxyProvider:
        if proxy_provider.value == provider_lower:
            return manager.switch_provider(proxy_provider)

    logger.error(f"Unknown provider: {provider}")
    return False


def get_proxy_status() -> dict:
    """Get status of all proxy providers."""
    manager = get_proxy_manager()
    return {
        "active": manager._active_provider.value,
        "providers": manager.list_providers(),
    }
