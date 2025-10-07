import os
import requests

from src.crawler.origin_proxy import enable_origin_proxy, disable_origin_proxy


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
    r = s.get('https://example.com/path?x=1')

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
