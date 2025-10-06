"""Origin-style proxy adapter for requests.

This module provides an adapter that converts standard HTTP requests to
origin-style proxy endpoint calls (e.g., /?url=...). This allows the
crawler to work with proxies that expect requests to a specific endpoint
rather than standard HTTP CONNECT proxying.

Usage:
    from src.utils.proxy_adapter import OriginProxyAdapter
    
    adapter = OriginProxyAdapter(
        proxy_url="http://proxy.example.com:8080",
        username="user",
        password="pass"
    )
    
    # Wrap a requests session
    wrapped_session = adapter.wrap_session(session)
    
    # Use the wrapped session normally
    response = wrapped_session.get("https://example.com")
"""

import logging
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlparse

import requests

logger = logging.getLogger(__name__)


class OriginProxyAdapter:
    """Adapter to convert standard HTTP requests to origin-style proxy calls."""
    
    def __init__(
        self,
        proxy_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize the origin proxy adapter.
        
        Args:
            proxy_url: Base URL of the proxy endpoint (e.g., "http://proxy:8080")
            username: Optional basic auth username
            password: Optional basic auth password
        """
        self.proxy_url = proxy_url.rstrip("/")
        self.username = username
        self.password = password
        self.auth = (username, password) if username and password else None
        
        logger.info(
            f"Initialized OriginProxyAdapter with proxy: {self.proxy_url}, "
            f"auth: {'enabled' if self.auth else 'disabled'}"
        )
    
    def wrap_session(self, session: requests.Session) -> requests.Session:
        """Wrap a requests.Session to use origin-style proxy.
        
        This modifies the session's request method to route through the
        origin-style proxy endpoint while preserving headers and auth.
        
        Args:
            session: The requests.Session to wrap
            
        Returns:
            The same session object (modified in-place)
        """
        # Store original request method - get the unbound method
        original_request = type(session).request
        adapter_self = self  # Capture self for the closure
        
        def proxied_request(self_session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
            """Intercept and route requests through origin-style proxy."""
            # Build the proxy endpoint URL with the target URL as a parameter
            proxy_endpoint = f"{adapter_self.proxy_url}/?url={quote(url, safe='')}"
            
            # Apply proxy auth if configured (overriding any existing auth)
            if adapter_self.auth:
                kwargs["auth"] = adapter_self.auth
            
            # Preserve all other kwargs (headers, timeout, etc.)
            logger.debug(
                f"Routing {method.upper()} {url} through origin proxy: "
                f"{adapter_self.proxy_url}"
            )
            
            # Make the request to the proxy endpoint
            return original_request(self_session, method, proxy_endpoint, **kwargs)
        
        # Replace the session's request method
        import types
        session.request = types.MethodType(proxied_request, session)  # type: ignore
        
        return session


def create_origin_proxy_session(
    base_session: Optional[requests.Session] = None,
    proxy_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> requests.Session:
    """Create or wrap a session with origin-style proxy support.
    
    This is a convenience function that creates a new session if needed
    and applies the origin proxy adapter.
    
    Args:
        base_session: Optional existing session to wrap (creates new if None)
        proxy_url: Proxy endpoint URL
        username: Optional basic auth username
        password: Optional basic auth password
        
    Returns:
        A requests.Session configured to use the origin-style proxy
    """
    if base_session is None:
        base_session = requests.Session()
    
    if not proxy_url:
        logger.warning("No proxy URL provided, returning unwrapped session")
        return base_session
    
    adapter = OriginProxyAdapter(proxy_url, username, password)
    return adapter.wrap_session(base_session)
