import logging
import os

import pytest
import requests

from src.crawler.origin_proxy import disable_origin_proxy, enable_origin_proxy


def test_enable_origin_proxy_rewrites_url_and_sets_auth(monkeypatch):
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured['method'] = method
        captured['url'] = url
        captured['kwargs'] = kwargs
        class R:
            status_code = 200
            text = 'ok'
        return R()

    # install fake original request
    s.request = fake_request  # type: ignore[assignment]

    # set env to enable origin proxy
    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')
    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.test:9999')
    monkeypatch.setenv('PROXY_USERNAME', 'user1')
    monkeypatch.setenv('PROXY_PASSWORD', 'pw')

    enable_origin_proxy(s)

    # call through session.get which uses session.request
    s.get('https://example.com/path?x=1')

    assert 'proxy.test' in captured['url']
    assert 'example.com' in captured['url']
    assert 'auth' in captured['kwargs']
    assert captured['kwargs']['auth'][0] == 'user1'
    headers = captured['kwargs'].get('headers', {})
    assert headers.get('Proxy-Authorization', '').startswith('Basic ')
    assert headers.get('Authorization', '').startswith('Basic ')

    disable_origin_proxy(s)


def test_metadata_url_bypasses_proxy(monkeypatch):
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured['url'] = url

        class R:
            status_code = 200
            text = ''

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv('USE_ORIGIN_PROXY', 'true')
    monkeypatch.delenv('ORIGIN_PROXY_BYPASS', raising=False)
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)

    enable_origin_proxy(s)
    s.get('http://metadata.google.internal/computeMetadata/v1')

    assert captured['url'] == 'http://metadata.google.internal/computeMetadata/v1'

    disable_origin_proxy(s)


def test_metadata_prepared_request_bypasses_proxy(monkeypatch):
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured['url'] = url

        class R:
            status_code = 200
            text = ''

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv('USE_ORIGIN_PROXY', 'true')
    enable_origin_proxy(s)

    prepared = requests.Request(
        'GET',
        'http://metadata.google.internal/computeMetadata/v1',
    ).prepare()
    s.request('GET', prepared)  # type: ignore[arg-type]

    assert captured['url'] is prepared

    disable_origin_proxy(s)


def test_proxy_usage_is_logged(monkeypatch, caplog):
    """Test that proxy usage is logged with authentication status."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = 'ok'

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')
    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.test:9999')
    monkeypatch.setenv('PROXY_USERNAME', 'user1')
    monkeypatch.setenv('PROXY_PASSWORD', 'pw')

    enable_origin_proxy(s)

    with caplog.at_level(logging.INFO):
        _ = s.get('https://example.com/path?x=1')

    # Check that proxy usage is logged
    assert any('🔀 Proxying GET' in record.message for record in caplog.records)
    assert any('example.com' in record.message for record in caplog.records)
    assert any('auth: yes' in record.message for record in caplog.records)
    assert any('✓ Proxy response 200' in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_missing_credentials_logged(monkeypatch, caplog):
    """Test that missing credentials are flagged in logs."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = 'ok'

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')
    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.test:9999')
    monkeypatch.delenv('PROXY_USERNAME', raising=False)
    monkeypatch.delenv('PROXY_PASSWORD', raising=False)

    enable_origin_proxy(s)

    with caplog.at_level(logging.INFO):
        _ = s.get('https://example.com/path?x=1')

    # Check that missing credentials are logged
    missing_creds_logged = any(
        'NO - MISSING CREDENTIALS' in record.message
        for record in caplog.records
    )
    assert missing_creds_logged

    disable_origin_proxy(s)


def test_bypass_decision_logged(monkeypatch, caplog):
    """Test that bypass decisions are logged."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = 'ok'

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv('USE_ORIGIN_PROXY', 'true')

    enable_origin_proxy(s)

    with caplog.at_level(logging.DEBUG):
        _ = s.get('http://metadata.google.internal/computeMetadata/v1')

    # Check that bypass is logged
    assert any('Origin proxy bypassed' in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_proxy_error_logged(monkeypatch, caplog):
    """Test that proxy errors are logged with details."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):
        raise requests.exceptions.ConnectionError("Connection refused")

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')
    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.test:9999')
    monkeypatch.setenv('PROXY_USERNAME', 'user1')
    monkeypatch.setenv('PROXY_PASSWORD', 'pw')

    enable_origin_proxy(s)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(requests.exceptions.ConnectionError):
            s.get('https://example.com/path')

    # Check that error is logged
    assert any('✗ Proxy request failed' in record.message for record in caplog.records)
    assert any('example.com' in record.message for record in caplog.records)
    assert any('ConnectionError' in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_proxy_disabled_logged(monkeypatch, caplog):
    """Test that disabled proxy is logged."""
    s = requests.Session()

    def fake_request(method, url, *args, **kwargs):

        class R:
            status_code = 200
            text = 'ok'

        return R()

    s.request = fake_request  # type: ignore[assignment]

    # Don't set USE_ORIGIN_PROXY
    monkeypatch.delenv('USE_ORIGIN_PROXY', raising=False)

    enable_origin_proxy(s)

    with caplog.at_level(logging.DEBUG):
        _ = s.get('https://example.com/path')

    # Check that proxy disabled is logged
    assert any('Origin proxy disabled' in record.message for record in caplog.records)

    disable_origin_proxy(s)


def test_proxy_kiesow_bypassed(monkeypatch):
    """Test that proxy.kiesow.net itself is always bypassed to prevent recursion."""
    s = requests.Session()

    captured = {}

    def fake_request(method, url, *args, **kwargs):
        captured['url'] = url

        class R:
            status_code = 200
            text = ''

        return R()

    s.request = fake_request  # type: ignore[assignment]

    monkeypatch.setenv('USE_ORIGIN_PROXY', 'true')
    monkeypatch.setenv('ORIGIN_PROXY_URL', 'http://proxy.kiesow.net:23432')

    enable_origin_proxy(s)

    # Request to proxy.kiesow.net itself should be bypassed
    s.get('http://proxy.kiesow.net:23432/?url=test')

    # URL should not be rewritten (not proxied through itself)
    assert captured['url'] == 'http://proxy.kiesow.net:23432/?url=test'

    disable_origin_proxy(s)
