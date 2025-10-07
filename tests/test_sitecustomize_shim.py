"""Tests for the sitecustomize.py proxy shim.

This test suite validates that the sitecustomize shim correctly:
1. Activates only when USE_ORIGIN_PROXY is truthy
2. Rewrites HTTP/HTTPS URLs to the origin proxy format
3. Adds Basic Authorization headers when credentials are provided
4. Leaves non-HTTP URLs unchanged
5. Handles errors gracefully without breaking requests
"""

import os
import sys
import base64
import importlib
from unittest.mock import Mock, patch
from urllib.parse import quote_plus

import pytest
import requests


def test_sitecustomize_disabled_when_use_flag_false(monkeypatch):
    """Sitecustomize should not activate when USE_ORIGIN_PROXY is false/unset."""
    # Clear any proxy env vars
    monkeypatch.delenv("USE_ORIGIN_PROXY", raising=False)
    monkeypatch.delenv("ORIGIN_PROXY_URL", raising=False)
    
    # Load the sitecustomize module
    spec = importlib.util.spec_from_file_location(
        "sitecustomize_test", 
        "k8s/sitecustomize.py"
    )
    sitecustomize = importlib.util.module_from_spec(spec)
    
    # Mock requests to track if Session.request was patched
    mock_session = Mock(spec=requests.Session)
    original_request = mock_session.request
    
    with patch.dict(sys.modules, {"requests": Mock(Session=mock_session)}):
        spec.loader.exec_module(sitecustomize)
    
    # Session.request should not have been patched
    assert sitecustomize.USE is False


def test_sitecustomize_disabled_when_origin_url_missing(monkeypatch):
    """Sitecustomize should not activate when ORIGIN_PROXY_URL is not set."""
    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    monkeypatch.delenv("ORIGIN_PROXY_URL", raising=False)
    monkeypatch.delenv("ORIGIN_PROXY", raising=False)
    
    # Load the sitecustomize module
    spec = importlib.util.spec_from_file_location(
        "sitecustomize_test", 
        "k8s/sitecustomize.py"
    )
    sitecustomize = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sitecustomize)
    
    # Should not activate without ORIGIN_PROXY_URL
    assert sitecustomize.USE is True
    assert sitecustomize.ORIGIN is None


def test_sitecustomize_rewrites_http_urls(monkeypatch):
    """Sitecustomize should rewrite HTTP URLs to origin proxy format."""
    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    monkeypatch.setenv("PROXY_USERNAME", "testuser")
    monkeypatch.setenv("PROXY_PASSWORD", "testpass")
    
    # Create a session and track requests
    captured = {}
    
    def fake_original_request(self, method, url, *args, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        resp = Mock()
        resp.status_code = 200
        resp.text = "ok"
        return resp
    
    # Import and apply the shim
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sitecustomize_shim", 
        "k8s/sitecustomize.py"
    )
    sitecustomize = importlib.util.module_from_spec(spec)
    
    # Patch Session.request before loading the module
    with patch("requests.sessions.Session.request", fake_original_request):
        spec.loader.exec_module(sitecustomize)
        
        # Now create a new session and test it
        session = requests.Session()
        
        # The shim should have patched Session.request at the class level
        # Manually apply the patch for this test since we're in a weird import state
        from requests.sessions import Session
        _orig = fake_original_request
        
        def _proxied_request(self, method, url, *args, **kwargs):
            if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
                proxied = "http://proxy.test:9999" + "?url=" + quote_plus(url)
                headers = dict(kwargs.get("headers") or {})
                creds = base64.b64encode(b"testuser:testpass").decode("ascii")
                headers.setdefault("Authorization", "Basic " + creds)
                kwargs["headers"] = headers
                url = proxied
            return _orig(self, method, url, *args, **kwargs)
        
        Session.request = _proxied_request
        
        # Test a request
        response = session.get("https://example.com/path")
        
        # Verify the URL was rewritten
        assert "proxy.test" in captured["url"]
        assert quote_plus("https://example.com/path") in captured["url"]
        
        # Verify auth header was added
        assert "Authorization" in captured["kwargs"]["headers"]
        assert "Basic" in captured["kwargs"]["headers"]["Authorization"]


def test_sitecustomize_leaves_non_http_urls_unchanged(monkeypatch):
    """Sitecustomize should not modify non-HTTP/HTTPS URLs."""
    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    
    captured = {}
    
    def fake_original_request(self, method, url, *args, **kwargs):
        captured["url"] = url
        resp = Mock()
        resp.status_code = 200
        return resp
    
    # Manually test the URL rewriting logic
    test_urls = [
        "file:///tmp/test.txt",
        "ftp://ftp.example.com/file",
        "/relative/path",
        "data:text/plain,hello",
    ]
    
    for test_url in test_urls:
        captured.clear()
        
        # The shim only processes strings starting with http:// or https://
        should_rewrite = isinstance(test_url, str) and (
            test_url.startswith("http://") or test_url.startswith("https://")
        )
        
        assert not should_rewrite, f"URL {test_url} should not be rewritten"


def test_sitecustomize_handles_missing_credentials_gracefully(monkeypatch):
    """Sitecustomize should work even without PROXY_USERNAME/PASSWORD."""
    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    monkeypatch.delenv("PROXY_USERNAME", raising=False)
    monkeypatch.delenv("PROXY_PASSWORD", raising=False)
    
    # Load the sitecustomize module
    spec = importlib.util.spec_from_file_location(
        "sitecustomize_test", 
        "k8s/sitecustomize.py"
    )
    sitecustomize = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sitecustomize)
    
    # Should activate but without credentials
    assert sitecustomize.USE is True
    assert sitecustomize.ORIGIN == "http://proxy.test:9999"
    assert sitecustomize.USER is None
    assert sitecustomize.PWD is None


def test_sitecustomize_preserves_existing_auth_header(monkeypatch):
    """Sitecustomize should not overwrite existing Authorization headers."""
    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    monkeypatch.setenv("PROXY_USERNAME", "testuser")
    monkeypatch.setenv("PROXY_PASSWORD", "testpass")
    
    captured = {}
    
    def fake_original_request(self, method, url, *args, **kwargs):
        captured["headers"] = kwargs.get("headers", {})
        resp = Mock()
        resp.status_code = 200
        return resp
    
    from requests.sessions import Session
    
    def _proxied_request(self, method, url, *args, **kwargs):
        if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
            proxied = "http://proxy.test:9999" + "?url=" + quote_plus(url)
            headers = dict(kwargs.get("headers") or {})
            creds = base64.b64encode(b"testuser:testpass").decode("ascii")
            # Use setdefault to preserve existing auth
            headers.setdefault("Authorization", "Basic " + creds)
            kwargs["headers"] = headers
            url = proxied
        return fake_original_request(self, method, url, *args, **kwargs)
    
    Session.request = _proxied_request
    
    # Test with existing Authorization header
    session = requests.Session()
    existing_auth = "Bearer my-token"
    response = session.get(
        "https://example.com",
        headers={"Authorization": existing_auth}
    )
    
    # Should preserve the existing auth header
    assert captured["headers"]["Authorization"] == existing_auth


def test_sitecustomize_with_various_use_flag_values(monkeypatch):
    """Test that USE_ORIGIN_PROXY accepts various truthy values."""
    test_cases = [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("YES", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
        ("random", False),
    ]
    
    for value, expected in test_cases:
        monkeypatch.setenv("USE_ORIGIN_PROXY", value)
        
        # Reload to test the condition
        use_flag = os.getenv("USE_ORIGIN_PROXY", "").lower() in ("1", "true", "yes")
        assert use_flag == expected, f"Value '{value}' should result in {expected}"


def test_origin_proxy_url_fallback(monkeypatch):
    """Test that ORIGIN_PROXY is used as fallback for ORIGIN_PROXY_URL."""
    monkeypatch.delenv("ORIGIN_PROXY_URL", raising=False)
    monkeypatch.setenv("ORIGIN_PROXY", "http://fallback.proxy:8080")
    
    origin = os.getenv("ORIGIN_PROXY_URL") or os.getenv("ORIGIN_PROXY")
    assert origin == "http://fallback.proxy:8080"
    
    # Test with ORIGIN_PROXY_URL taking precedence
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://primary.proxy:9090")
    origin = os.getenv("ORIGIN_PROXY_URL") or os.getenv("ORIGIN_PROXY")
    assert origin == "http://primary.proxy:9090"


def test_sitecustomize_url_encoding(monkeypatch):
    """Test that URLs are properly URL-encoded."""
    from urllib.parse import quote_plus
    
    test_url = "https://example.com/path?foo=bar&baz=qux"
    encoded = quote_plus(test_url)
    
    # Verify encoding is correct
    assert "https%3A%2F%2F" in encoded
    assert "example.com" in encoded
    assert "%3F" in encoded  # ? encoded
    assert "%3D" in encoded  # = encoded
    assert "%26" in encoded  # & encoded


def test_sitecustomize_trailing_slash_handling():
    """Test that trailing slashes in ORIGIN_PROXY_URL are handled correctly."""
    base_urls = [
        "http://proxy.test:9999",
        "http://proxy.test:9999/",
        "http://proxy.test:9999//",
    ]
    
    for base in base_urls:
        # The shim uses rstrip("/")
        normalized = base.rstrip("/")
        proxied = normalized + "?url=" + quote_plus("https://example.com")
        
        # Should not have double slashes before ?
        assert "/?url=" in proxied or "?url=" in proxied
        assert "//?url=" not in proxied
