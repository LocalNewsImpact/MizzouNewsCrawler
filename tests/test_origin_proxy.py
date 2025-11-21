import logging
import os

import pytest
import requests

from src.crawler.origin_proxy import disable_origin_proxy, enable_origin_proxy


def test_enable_origin_proxy_rewrites_url_and_sets_auth(monkeypatch):
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs

        class R:
            status_code = 200
            text = "ok"

        return R()

    # install fake original request
    s.request = fake_request  # type: ignore[assignment]

    # set env to enable origin proxy
    monkeypatch.setenv("USE_ORIGIN_PROXY", "1")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    monkeypatch.setenv("PROXY_USERNAME", "user1")
    monkeypatch.setenv("PROXY_PASSWORD", "pw")

    enable_origin_proxy(s)

    # call through session.get which uses session.request
    s.get("https://example.com/path?x=1")

    assert "proxy.test" in captured["url"]
    assert "example.com" in captured["url"]
    assert "auth" in captured["kwargs"]
    assert captured["kwargs"]["auth"][0] == "user1"
    headers = captured["kwargs"].get("headers", {})
    assert headers.get("Proxy-Authorization", "").startswith("Basic ")
    assert headers.get("Authorization", "").startswith("Basic ")

    disable_origin_proxy(s)


def test_metadata_url_bypasses_proxy(monkeypatch):
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured["url"] = url

        class R:
            status_code = 200
            text = ""

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    monkeypatch.delenv("ORIGIN_PROXY_BYPASS", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    enable_origin_proxy(s)
    s.get("http://metadata.google.internal/computeMetadata/v1")

    assert captured["url"] == "http://metadata.google.internal/computeMetadata/v1"

    disable_origin_proxy(s)


def test_metadata_prepared_request_bypasses_proxy(monkeypatch):
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured["url"] = url

        class R:
            status_code = 200
            text = ""

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    enable_origin_proxy(s)

    prepared = requests.Request(
        "GET",
        "http://metadata.google.internal/computeMetadata/v1",
    ).prepare()
    s.request("GET", prepared)  # type: ignore[arg-type]

    assert captured["url"] is prepared

    disable_origin_proxy(s)


def test_proxy_usage_is_logged(monkeypatch, caplog):
    """Test that proxy usage is logged with authentication status."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = "ok"

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv("USE_ORIGIN_PROXY", "1")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    monkeypatch.setenv("PROXY_USERNAME", "user1")
    monkeypatch.setenv("PROXY_PASSWORD", "pw")

    enable_origin_proxy(s)

    with caplog.at_level(logging.INFO):
        _ = s.get("https://example.com/path?x=1")

    # Check that proxy usage is logged
    assert any("🔀 Proxying GET" in record.message for record in caplog.records)
    assert any("example.com" in record.message for record in caplog.records)
    assert any("auth: yes" in record.message for record in caplog.records)
    assert any("✓ Proxy response 200" in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_missing_credentials_logged(monkeypatch, caplog):
    """Test that missing credentials are flagged in logs."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = "ok"

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv("USE_ORIGIN_PROXY", "1")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    monkeypatch.delenv("PROXY_USERNAME", raising=False)
    monkeypatch.delenv("PROXY_PASSWORD", raising=False)

    enable_origin_proxy(s)

    with caplog.at_level(logging.INFO):
        _ = s.get("https://example.com/path?x=1")

    # Check that missing credentials are logged
    missing_creds_logged = any(
        "NO - MISSING CREDENTIALS" in record.message for record in caplog.records
    )
    assert missing_creds_logged

    disable_origin_proxy(s)


def test_bypass_decision_logged(monkeypatch, caplog):
    """Test that bypass decisions are logged."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = "ok"

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")

    enable_origin_proxy(s)

    with caplog.at_level(logging.DEBUG):
        _ = s.get("http://metadata.google.internal/computeMetadata/v1")

    # Check that bypass is logged
    assert any("Origin proxy bypassed" in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_proxy_error_logged(monkeypatch, caplog):
    """Test that proxy errors are logged with details."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):
        raise requests.exceptions.ConnectionError("Connection refused")

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv("USE_ORIGIN_PROXY", "1")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.test:9999")
    monkeypatch.setenv("PROXY_USERNAME", "user1")
    monkeypatch.setenv("PROXY_PASSWORD", "pw")

    enable_origin_proxy(s)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(requests.exceptions.ConnectionError):
            s.get("https://example.com/path")

    # Check that error is logged
    assert any("✗ Proxy request failed" in record.message for record in caplog.records)
    assert any("example.com" in record.message for record in caplog.records)
    assert any("ConnectionError" in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_proxy_disabled_logged(monkeypatch, caplog):
    """Test that disabled proxy is logged."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = "ok"

        return R()

    s.request = fake_request  # type: ignore[assignment]

    # Don't set USE_ORIGIN_PROXY
    monkeypatch.delenv("USE_ORIGIN_PROXY", raising=False)

    enable_origin_proxy(s)

    with caplog.at_level(logging.DEBUG):
        _ = s.get("https://example.com/path")

    # Check that proxy disabled is logged
    assert any("Origin proxy disabled" in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_proxy_kiesow_bypassed(monkeypatch):
    """Test that proxy.kiesow.net itself is always bypassed to prevent recursion."""
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured["url"] = url

        class R:
            status_code = 200
            text = ""

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv("USE_ORIGIN_PROXY", "true")
    monkeypatch.setenv("ORIGIN_PROXY_URL", "http://proxy.kiesow.net:23432")

    enable_origin_proxy(s)

    # Request to proxy.kiesow.net itself should be bypassed
    s.get("http://proxy.kiesow.net:23432/?url=test")

    # URL should not be rewritten (not proxied through itself)
    assert captured["url"] == "http://proxy.kiesow.net:23432/?url=test"

    disable_origin_proxy(s)


def test_extract_url_with_object_url_attribute():
    """Test _extract_url with object that has url attribute."""
    from src.crawler.origin_proxy import _extract_url

    class MockRequest:
        def __init__(self, url):
            self.url = url

    # Test with object that has url attribute
    obj = MockRequest("https://example.com")
    assert _extract_url(obj) == "https://example.com"

    # Test with object that has None url
    obj_none = MockRequest(None)
    assert _extract_url(obj_none) is None


def test_extract_url_with_string():
    """Test _extract_url with string input."""
    from src.crawler.origin_proxy import _extract_url

    assert _extract_url("https://example.com") == "https://example.com"


def test_extract_url_with_other_type():
    """Test _extract_url returns None for unsupported types."""
    from src.crawler.origin_proxy import _extract_url

    assert _extract_url(123) is None
    assert _extract_url([]) is None
    assert _extract_url({}) is None


def test_parse_bypass_hosts_with_env_vars(monkeypatch):
    """Test _parse_bypass_hosts reads from multiple env vars."""
    from src.crawler.origin_proxy import _parse_bypass_hosts

    monkeypatch.setenv("ORIGIN_PROXY_BYPASS", "example.com, test.local")
    monkeypatch.setenv("NO_PROXY", "internal.net")
    monkeypatch.setenv("no_proxy", "localhost")

    hosts = _parse_bypass_hosts()

    # Should contain all env var entries plus metadata hosts
    assert "example.com" in hosts
    assert "test.local" in hosts
    assert "internal.net" in hosts
    assert "localhost" in hosts
    assert "metadata.google.internal" in hosts


def test_parse_bypass_hosts_handles_empty_entries(monkeypatch):
    """Test _parse_bypass_hosts ignores empty entries."""
    from src.crawler.origin_proxy import _parse_bypass_hosts

    # Empty strings and whitespace should be ignored
    monkeypatch.setenv("ORIGIN_PROXY_BYPASS", "  , example.com ,  , test.local ,  ")

    hosts = _parse_bypass_hosts()

    assert "example.com" in hosts
    assert "test.local" in hosts
    # Empty strings shouldn't be in the set
    assert "" not in hosts
    assert "  " not in hosts


def test_should_bypass_with_url_parse_exception(monkeypatch):
    """Test _should_bypass handles urlparse exceptions."""
    from src.crawler.origin_proxy import _should_bypass

    # Mock urlparse to raise an exception
    import src.crawler.origin_proxy as proxy_module

    original_urlparse = proxy_module.urlparse

    def mock_urlparse_error(url):
        raise ValueError("Parse error")

    monkeypatch.setattr(proxy_module, "urlparse", mock_urlparse_error)

    # Should return False on exception
    assert _should_bypass("https://example.com") is False

    # Restore
    monkeypatch.setattr(proxy_module, "urlparse", original_urlparse)


def test_should_bypass_with_none_hostname():
    """Test _should_bypass handles URLs with no hostname."""
    from src.crawler.origin_proxy import _should_bypass

    # URL without hostname should not bypass
    assert _should_bypass("file:///path/to/file") is False


def test_should_bypass_with_none_url():
    """Test _should_bypass handles None URL input."""
    from src.crawler.origin_proxy import _should_bypass

    # None URL should not bypass
    assert _should_bypass(None) is False

    # Object that extracts to None should not bypass
    class ObjWithNoneUrl:
        url = None

    assert _should_bypass(ObjWithNoneUrl()) is False


def test_should_bypass_with_domain_suffix(monkeypatch):
    """Test _should_bypass supports domain suffix matches."""
    from src.crawler.origin_proxy import _should_bypass

    monkeypatch.setenv("ORIGIN_PROXY_BYPASS", ".internal,.local")

    # Should bypass URLs ending with .internal or .local
    assert _should_bypass("https://api.internal") is True
    assert _should_bypass("https://test.local") is True
    assert _should_bypass("https://example.com") is False


def test_enable_origin_proxy_already_installed():
    """Test enable_origin_proxy doesn't double-wrap."""
    s = requests.Session()

    # Install once
    enable_origin_proxy(s)
    original_request = s.request

    # Try to install again
    enable_origin_proxy(s)

    # Should be the same (not double-wrapped)
    assert s.request is original_request


def test_disable_origin_proxy():
    """Test disable_origin_proxy removes wrapper."""
    s = requests.Session()
    original_request = s.request

    # Install proxy
    enable_origin_proxy(s)

    # Request should be wrapped
    assert s.request != original_request

    # Disable proxy
    disable_origin_proxy(s)

    # Should be restored or at least disabled
    assert not getattr(s, "_origin_proxy_installed", False)
