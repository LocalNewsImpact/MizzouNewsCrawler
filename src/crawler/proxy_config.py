"""Proxy configuration with multiple provider support and master switch."""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ProxyProvider(Enum):
    """Available proxy providers."""
    
    # Origin-style proxy (current default)
    ORIGIN = "origin"
    
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
    
    # Decodo ISP proxy
    DECODO = "decodo"
    
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
        
        # Origin proxy (current default)
        self.configs[ProxyProvider.ORIGIN] = ProxyConfig(
            provider=ProxyProvider.ORIGIN,
            enabled=True,  # Always available
            url=os.getenv("ORIGIN_PROXY_URL", "http://proxy.kiesow.net:23432"),
            username=os.getenv("PROXY_USERNAME"),
            password=os.getenv("PROXY_PASSWORD"),
        )
        
        # Direct connection (no proxy)
        self.configs[ProxyProvider.DIRECT] = ProxyConfig(
            provider=ProxyProvider.DIRECT,
            enabled=True,  # Always available
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
        
        # Decodo ISP proxy with port-based IP rotation
        # Ports 10001-10010 provide different IPs for rotation
        decodo_username = os.getenv("DECODO_USERNAME", "user-sp8z2fzi1e-country-us")
        decodo_password = os.getenv("DECODO_PASSWORD", "qg_hJ7reok8e5F7BHg")
        decodo_host = os.getenv("DECODO_HOST", "isp.decodo.com")
        decodo_country = os.getenv("DECODO_COUNTRY", "us")
        
        # Use rotating ports (10001-10010) for IP rotation, or default port for sticky
        use_port_rotation = os.getenv("DECODO_ROTATE_IP", "true").lower() == "true"
        
        if use_port_rotation:
            # Randomly select from rotation port range for this session
            import random
            decodo_port = str(random.randint(10001, 10010))
        else:
            decodo_port = os.getenv("DECODO_PORT", "10000")
        
        # Decodo URL with credentials - using HTTPS for encrypted proxy auth
        decodo_url = (
            f"https://{decodo_username}:{decodo_password}@"
            f"{decodo_host}:{decodo_port}"
        )
        
        self.configs[ProxyProvider.DECODO] = ProxyConfig(
            provider=ProxyProvider.DECODO,
            enabled=True,  # Always available with default credentials
            url=decodo_url,
            # Don't set username/password here - already in URL
            username=None,
            password=None,
            options={
                "country": decodo_country,
                "host": decodo_host,
                "port": decodo_port,
                "rotate_ip": use_port_rotation,
                "port_range": "10001-10010" if use_port_rotation else None,
            },
        )
    
    def _get_active_provider(self) -> ProxyProvider:
        """Determine active provider from PROXY_PROVIDER env var."""
        provider_name = os.getenv("PROXY_PROVIDER", "origin").lower()
        
        # Map common aliases
        aliases = {
            "none": ProxyProvider.DIRECT,
            "off": ProxyProvider.DIRECT,
            "disabled": ProxyProvider.DIRECT,
            "origin": ProxyProvider.ORIGIN,
            "default": ProxyProvider.ORIGIN,
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
            "decodo": ProxyProvider.DECODO,
        }
        
        provider = aliases.get(provider_name)
        if provider is None:
            try:
                provider = ProxyProvider(provider_name)
            except ValueError:
                logger.warning(
                    f"Unknown proxy provider '{provider_name}', falling back to ORIGIN"
                )
                provider = ProxyProvider.ORIGIN
        
        # Verify provider is available
        if provider not in self.configs or not self.configs[provider].enabled:
            logger.warning(
                f"Provider {provider.value} not configured, falling back to ORIGIN"
            )
            provider = ProxyProvider.ORIGIN
        
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
        
        logger.info(
            f"🔄 Switched proxy: {old_provider.value} → {provider.value}"
        )
        return True
    
    def list_providers(self) -> dict:
        """List all available providers with their status."""
        return {
            provider.value: {
                "enabled": config.enabled,
                "url": config.url or "N/A",
                "health": config.health_status,
                "success_rate": f"{config.success_rate:.1f}%",
                "requests": config.success_count + config.failure_count,
                "avg_response_time": f"{config.avg_response_time:.2f}s",
            }
            for provider, config in self.configs.items()
        }
    
    def record_success(self, provider: Optional[ProxyProvider] = None, 
                      response_time: float = 0.0):
        """Record a successful request."""
        provider = provider or self._active_provider
        if provider in self.configs:
            config = self.configs[provider]
            config.success_count += 1
            
            # Update rolling average response time
            total = config.success_count + config.failure_count
            config.avg_response_time = (
                (config.avg_response_time * (total - 1) + response_time) / total
            )
    
    def record_failure(self, provider: Optional[ProxyProvider] = None):
        """Record a failed request."""
        provider = provider or self._active_provider
        if provider in self.configs:
            self.configs[provider].failure_count += 1
    
    def get_requests_proxies(self) -> Optional[dict]:
        """
        Get proxy configuration in requests library format.
        For Decodo with IP rotation, returns URL with rotating port.
        
        Returns:
            dict: Proxy config for requests library, or None for ORIGIN/DIRECT
        """
        config = self.get_active_config()
        
        # Origin proxy uses custom adapter, not requests proxies
        if config.provider == ProxyProvider.ORIGIN:
            return None
        
        # Direct connection uses no proxy
        if config.provider == ProxyProvider.DIRECT:
            return None
        
        # Decodo with IP rotation - use rotating port
        if config.provider == ProxyProvider.DECODO:
            rotating_url = self.get_rotating_decodo_url()
            if rotating_url:
                return {
                    "http": rotating_url,
                    "https": rotating_url,
                }
        
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
    
    def get_rotating_decodo_url(self) -> Optional[str]:
        """
        Get Decodo proxy URL with rotating port (10001-10010) for IP rotation.
        Each call returns a different port from the range.
        
        Returns:
            str: Proxy URL with rotated port, or None if not using Decodo
        """
        config = self.get_active_config()
        
        if config.provider != ProxyProvider.DECODO:
            return None
        
        # Check if rotation is enabled
        if not config.options or not config.options.get("rotate_ip", False):
            return config.url
        
        # Get rotation parameters
        import random
        port = random.randint(10001, 10010)
        username = os.getenv("DECODO_USERNAME", "user-sp8z2fzi1e-country-us")
        password = os.getenv("DECODO_PASSWORD", "qg_hJ7reok8e5F7BHg")
        host = config.options.get("host", "isp.decodo.com") if config.options else "isp.decodo.com"
        
        return f"https://{username}:{password}@{host}:{port}"
    
    def should_use_origin_proxy(self) -> bool:
        """Check if origin proxy should be enabled."""
        return self._active_provider == ProxyProvider.ORIGIN
    
    def get_origin_proxy_url(self) -> Optional[str]:
        """Get origin proxy URL if active."""
        if self._active_provider == ProxyProvider.ORIGIN:
            return self.configs[ProxyProvider.ORIGIN].url
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
