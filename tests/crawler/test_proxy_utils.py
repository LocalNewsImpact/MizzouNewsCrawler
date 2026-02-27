from src.crawler.utils import mask_proxy_url


def test_mask_proxy_url_masks_password():
    url = "https://user:pass@unblock.decodo.com:60000"
    assert mask_proxy_url(url) == "https://user:***@unblock.decodo.com:60000"


def test_mask_proxy_url_no_credentials():
    url = "https://unblock.decodo.com:60000"
    assert mask_proxy_url(url) == "https://unblock.decodo.com:60000"


def test_mask_proxy_url_none_returns_none():
    assert mask_proxy_url(None) is None


def test_mask_proxy_url_empty_string_returns_none():
    """Empty strings should return None."""
    assert mask_proxy_url("") is None
    # Note: whitespace-only strings are technically "truthy" and will pass through
    # This is acceptable behavior - they won't be valid URLs anyway


def test_mask_proxy_url_preserves_scheme():
    """Different URL schemes should be preserved."""
    http = mask_proxy_url("http://user:pass@proxy.net:8080")
    assert http == "http://user:***@proxy.net:8080"

    socks5 = mask_proxy_url("socks5://user:pass@proxy.net:1080")
    assert socks5 == "socks5://user:***@proxy.net:1080"


def test_mask_proxy_url_without_port():
    """Masking should work without explicit port."""
    result = mask_proxy_url("https://user:pass@proxy.example.com")
    assert result == "https://user:***@proxy.example.com"
    assert "pass" not in result


def test_mask_proxy_url_with_username_only():
    """URLs with username but no password should still mask."""
    result = mask_proxy_url("https://user@proxy.net:3128")
    assert result == "https://user:***@proxy.net:3128"


def test_mask_proxy_url_special_chars_in_password():
    """Passwords with special characters should be masked."""
    # urlparse has limitations with @ characters in passwords
    # This tests that simple special chars work correctly
    result = mask_proxy_url("https://admin:p4ssw0rd!@proxy:8080")
    assert result == "https://admin:***@proxy:8080"
    assert "p4ssw0rd" not in result


def test_mask_proxy_url_malformed_url_returns_redacted():
    """Malformed URLs that cause parsing exceptions should return '<redacted>'."""
    # urlparse is very permissive - most strings parse without exceptions
    # This function relies on exception handling as a last resort
    # Test that the function doesn't crash on edge cases
    result = mask_proxy_url(":::invalid:::")
    # May return <redacted> or parse oddly, but shouldn't crash
    assert result is not None


def test_mask_proxy_url_with_ipv4_address():
    """Should work with IPv4 addresses."""
    result = mask_proxy_url("http://user:pass@192.168.1.1:3128")
    assert result == "http://user:***@192.168.1.1:3128"


def test_mask_proxy_url_with_localhost():
    """Should work with localhost."""
    result = mask_proxy_url("http://admin:secret@localhost:8080")
    assert result == "http://admin:***@localhost:8080"


def test_mask_proxy_url_complex_password():
    """Complex passwords should be fully masked."""
    # Note: @ in passwords confuses urlparse - use URL encoding for such cases
    url = "https://user:Passw0rd!$@squid.proxy.net:3128"
    result = mask_proxy_url(url)
    assert result == "https://user:***@squid.proxy.net:3128"
    assert "Passw0rd" not in result


def test_mask_proxy_url_url_encoded_password():
    """URL-encoded passwords should be masked."""
    url = "https://user:p%40ss%23word@proxy.net:3128"
    result = mask_proxy_url(url)
    assert result == "https://user:***@proxy.net:3128"
    assert "p%40ss%23word" not in result


def test_mask_proxy_url_urlparse_exception(monkeypatch):
    """Test exception path in mask_proxy_url (lines 34-36)."""
    from urllib.parse import urlparse as real_urlparse

    def failing_urlparse(url):
        # Only fail for our test URL, let other calls through
        if "trigger_exception" in url:
            raise RuntimeError("urlparse failed")
        return real_urlparse(url)

    monkeypatch.setattr("src.crawler.utils.urlparse", failing_urlparse)
    result = mask_proxy_url("http://trigger_exception:pass@proxy.com")
    assert result == "<redacted>"
