"""Tests for origin-style proxy adapter."""

from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from src.utils.proxy_adapter import OriginProxyAdapter, create_origin_proxy_session


class TestOriginProxyAdapter:
    """Test the OriginProxyAdapter class."""
    
    def test_init_without_auth(self):
        """Test adapter initialization without authentication."""
        adapter = OriginProxyAdapter("http://proxy.example.com:8080")
        
        assert adapter.proxy_url == "http://proxy.example.com:8080"
        assert adapter.username is None
        assert adapter.password is None
        assert adapter.auth is None
    
    def test_init_with_auth(self):
        """Test adapter initialization with authentication."""
        adapter = OriginProxyAdapter(
            "http://proxy.example.com:8080",
            username="user",
            password="pass"
        )
        
        assert adapter.proxy_url == "http://proxy.example.com:8080"
        assert adapter.username == "user"
        assert adapter.password == "pass"
        assert adapter.auth == ("user", "pass")
    
    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is removed from proxy URL."""
        adapter = OriginProxyAdapter("http://proxy.example.com:8080/")
        assert adapter.proxy_url == "http://proxy.example.com:8080"
    
    def test_wrap_session_modifies_request_method(self):
        """Test that wrapping a session modifies its request method."""
        session = requests.Session()
        original_request = session.request
        
        adapter = OriginProxyAdapter("http://proxy.example.com:8080")
        wrapped_session = adapter.wrap_session(session)
        
        # Session should be modified in place
        assert wrapped_session is session
        # Request method should be different
        assert session.request != original_request
    
    def test_proxied_request_url_encoding(self):
        """Test that target URLs are properly encoded in proxy requests."""
        session = requests.Session()
        adapter = OriginProxyAdapter("http://proxy.example.com:8080")
        
        # Store original for comparison
        original_request = type(session).request
        adapter.wrap_session(session)
        
        # Session request method should be wrapped
        assert session.request.__func__ != original_request  # type: ignore
        
        # Mock at the adapter level to capture the transformed URL
        with patch('requests.adapters.HTTPAdapter.send') as mock_send:
            # Create a real Response object
            mock_response = requests.Response()
            mock_response.status_code = 200
            mock_response._content = b"success"
            mock_response.url = "http://proxy.example.com:8080/?url=..."
            mock_send.return_value = mock_response
            
            # Make a request through the wrapped session
            target_url = "https://example.com/article?id=123"
            response = session.get(target_url)
            
            # Verify the request was transformed
            assert mock_send.called
            prepared_request = mock_send.call_args[0][0]
            actual_url = prepared_request.url
            
            # Parse the proxy URL
            parsed = urlparse(actual_url)
            assert parsed.scheme == "http"
            assert parsed.netloc == "proxy.example.com:8080"
            
            # Check that the target URL is in the query string
            query_params = parse_qs(parsed.query)
            assert "url" in query_params
            assert query_params["url"][0] == target_url
    
    def test_proxied_request_preserves_headers(self):
        """Test that custom headers are preserved in proxied requests."""
        session = requests.Session()
        session.headers.update({"User-Agent": "TestBot/1.0"})
        
        adapter = OriginProxyAdapter("http://proxy.example.com:8080")
        adapter.wrap_session(session)
        
        with patch.object(session, 'request', wraps=session.request) as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_request.return_value = mock_response
            
            session.get("https://example.com", headers={"X-Custom": "value"})
            
            call_kwargs = mock_request.call_args[1]
            assert "headers" in call_kwargs
            assert call_kwargs["headers"]["X-Custom"] == "value"
    
    def test_proxied_request_applies_auth(self):
        """Test that proxy authentication is applied to requests."""
        session = requests.Session()
        adapter = OriginProxyAdapter(
            "http://proxy.example.com:8080",
            username="user",
            password="pass"
        )
        adapter.wrap_session(session)
        
        with patch('requests.adapters.HTTPAdapter.send') as mock_send:
            mock_response = requests.Response()
            mock_response.status_code = 200
            mock_response._content = b"success"
            mock_response.url = "http://proxy.example.com:8080"
            mock_send.return_value = mock_response
            
            session.get("https://example.com")
            
            # Check the prepared request has auth
            prepared_request = mock_send.call_args[0][0]
            # requests encodes auth into Authorization header
            assert "Authorization" in prepared_request.headers
    
    def test_proxied_request_overrides_existing_auth(self):
        """Test that proxy auth overrides any existing auth in the request."""
        session = requests.Session()
        adapter = OriginProxyAdapter(
            "http://proxy.example.com:8080",
            username="proxy_user",
            password="proxy_pass"
        )
        adapter.wrap_session(session)
        
        with patch('requests.adapters.HTTPAdapter.send') as mock_send:
            mock_response = requests.Response()
            mock_response.status_code = 200
            mock_response._content = b"success"
            mock_response.url = "http://proxy.example.com:8080"
            mock_send.return_value = mock_response
            
            # Try to pass different auth - it should be overridden
            session.get("https://example.com", auth=("other", "auth"))
            
            # The proxy auth should be in the Authorization header
            prepared_request = mock_send.call_args[0][0]
            assert "Authorization" in prepared_request.headers
            # Basic auth for proxy_user:proxy_pass
            import base64
            expected_auth = base64.b64encode(b"proxy_user:proxy_pass").decode('ascii')
            assert prepared_request.headers["Authorization"] == f"Basic {expected_auth}"


class TestCreateOriginProxySession:
    """Test the create_origin_proxy_session convenience function."""
    
    def test_creates_new_session(self):
        """Test that a new session is created if none provided."""
        session = create_origin_proxy_session(
            proxy_url="http://proxy.example.com:8080"
        )
        
        assert isinstance(session, requests.Session)
    
    def test_wraps_existing_session(self):
        """Test that an existing session is wrapped."""
        existing_session = requests.Session()
        existing_session.headers.update({"X-Custom": "value"})
        
        wrapped = create_origin_proxy_session(
            base_session=existing_session,
            proxy_url="http://proxy.example.com:8080"
        )
        
        # Should return the same session object
        assert wrapped is existing_session
        # Custom header should be preserved
        assert wrapped.headers["X-Custom"] == "value"
    
    def test_returns_unwrapped_without_proxy_url(self):
        """Test that session is returned unwrapped if no proxy URL."""
        session = requests.Session()
        result = create_origin_proxy_session(base_session=session)
        
        assert result is session
    
    def test_applies_auth_credentials(self):
        """Test that authentication credentials are applied."""
        with patch.object(OriginProxyAdapter, '__init__', return_value=None) as mock_init:
            with patch.object(OriginProxyAdapter, 'wrap_session') as mock_wrap:
                mock_wrap.return_value = MagicMock()
                
                create_origin_proxy_session(
                    proxy_url="http://proxy.example.com:8080",
                    username="user",
                    password="pass"
                )
                
                # Verify adapter was initialized with credentials
                mock_init.assert_called_once_with(
                    "http://proxy.example.com:8080",
                    "user",
                    "pass"
                )


class TestProxyAdapterIntegration:
    """Integration tests for the proxy adapter."""
    
    def test_end_to_end_request_flow(self):
        """Test complete request flow through the proxy adapter."""
        # Create a real session with the adapter
        session = requests.Session()
        adapter = OriginProxyAdapter("http://proxy.example.com:8080")
        adapter.wrap_session(session)
        
        # Mock the adapter send to avoid actual network calls
        with patch('requests.adapters.HTTPAdapter.send') as mock_send:
            mock_response = requests.Response()
            mock_response.status_code = 200
            mock_response._content = b"success"
            mock_response.url = "http://proxy.example.com:8080/?url=..."
            mock_send.return_value = mock_response
            
            # Make a GET request
            response = session.get("https://news.example.com/article")
            
            # Verify the request was routed correctly
            assert mock_send.called
            prepared_request = mock_send.call_args[0][0]
            
            # Check the URL points to proxy with encoded target
            actual_url = prepared_request.url
            assert actual_url.startswith("http://proxy.example.com:8080/?url=")
            assert "news.example.com" in actual_url
            
            # Check response is returned
            assert response.status_code == 200
            assert response.text == "success"
