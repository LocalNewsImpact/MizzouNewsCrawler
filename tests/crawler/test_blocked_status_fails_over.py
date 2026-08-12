"""A 403 is a failure of the proxy, not a successful fetch.

`requests` does not raise on 4xx, so `session.get()` returning a Cloudflare 403
looked exactly like a 200 to the old code, which reported `success=True` to the
proxy router unconditionally. The router therefore never backed the proxy off
for that domain, never failed over to the second Squid, and recorded the banned
address as healthy for precisely the domains where it was banned. Discovery
reported "no articles found" for sites that were only being refused at one IP.

Measured on 20 VTCNI sources that discovery had found nothing for: re-running
them through the other Squid alone produced 535 candidate URLs from 11 of them.

These tests assert on what the ROUTER IS TOLD, not just on the response handed
back. Reporting the wrong thing to the router is the entire bug, and it is
invisible from the return value -- which is why it survived in production.
"""

from __future__ import annotations

import types

import pytest
import requests

from src.crawler.discovery import BLOCKED_STATUS_CODES, NewsDiscovery
from src.crawler.proxy_config import ProxyManager
from src.crawler.proxy_router import RouterProxy

HOME = {"http": "http://home:3128", "https": "http://home:3128"}
MIZZOU = {"http": "http://mizzou:3128", "https": "http://mizzou:3128"}


class _Response:
    def __init__(self, status_code: int, text: str = "<html></html>"):
        self.status_code = status_code
        self.text = text


class _Session:
    """Returns a queued response per call, recording the proxies used."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict | None] = []

    def get(self, url, timeout=None, proxies=None):
        self.calls.append(proxies)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _ProxyManager:
    """Stubs only the config lookup; the selection logic is the real one.

    get_alternate_proxies is bound straight off ProxyManager so these tests
    exercise production's "is the other proxy actually different?" rule rather
    than a reimplementation of it that could drift.
    """

    get_alternate_proxies = ProxyManager.get_alternate_proxies

    def __init__(self, resolvable=None):
        # RouterProxy -> proxies dict
        self._resolvable = resolvable or {
            RouterProxy.HOME_SQUID: HOME,
            RouterProxy.MIZZOU_SQUID: MIZZOU,
        }

    def get_requests_proxies_for_router_proxy(self, router_proxy):
        return self._resolvable.get(router_proxy)


def _discovery(session, *, routed=RouterProxy.HOME_SQUID, manager=None):
    """A NewsDiscovery with the network and router stubbed, no __init__."""
    d = NewsDiscovery.__new__(NewsDiscovery)
    d.session = session
    d._fallback_session = session
    d.timeout = 5
    d.proxy_manager = manager or _ProxyManager()
    d.reported: list[tuple] = []

    d._router_proxies_for_domain = lambda domain: (HOME, routed)
    d._report_router_result = lambda domain, proxy, success, reason=None: (
        d.reported.append((proxy, success, reason))
    )
    d._note_capture_diagnosis = lambda url, html: None
    return d


class TestBlockedStatusIsReportedAsFailure:
    @pytest.mark.parametrize("status", sorted(BLOCKED_STATUS_CODES))
    def test_router_is_told_the_proxy_failed(self, status):
        session = _Session([_Response(status), _Response(200)])
        d = _discovery(session)

        d._fetch_with_ssl_fallback("https://example.com/")

        first_proxy, first_success, reason = d.reported[0]
        assert first_proxy is RouterProxy.HOME_SQUID
        assert first_success is False
        assert str(status) in reason

    def test_a_200_still_reports_success(self):
        session = _Session([_Response(200)])
        d = _discovery(session)

        d._fetch_with_ssl_fallback("https://example.com/")

        assert d.reported == [(RouterProxy.HOME_SQUID, True, None)]

    def test_404_is_not_treated_as_a_block(self):
        """The page is gone from every address -- retrying is pure waste."""
        session = _Session([_Response(404)])
        d = _discovery(session)

        response = d._fetch_with_ssl_fallback("https://example.com/")

        assert response.status_code == 404
        assert d.reported == [(RouterProxy.HOME_SQUID, True, None)]
        assert len(session.calls) == 1

    def test_503_is_not_treated_as_a_block(self):
        """An origin under strain should not get a second proxy's load too."""
        session = _Session([_Response(503)])
        d = _discovery(session)

        d._fetch_with_ssl_fallback("https://example.com/")

        assert len(session.calls) == 1


class TestRetryOnTheAlternateProxy:
    def test_blocked_request_is_retried_through_the_other_squid(self):
        session = _Session([_Response(403), _Response(200, "<html>real</html>")])
        d = _discovery(session)

        response = d._fetch_with_ssl_fallback("https://example.com/")

        assert [c for c in session.calls] == [HOME, MIZZOU]
        assert response.status_code == 200
        assert response.text == "<html>real</html>"

    def test_successful_retry_is_reported_against_the_proxy_that_worked(self):
        session = _Session([_Response(403), _Response(200)])
        d = _discovery(session)

        d._fetch_with_ssl_fallback("https://example.com/")

        assert d.reported == [
            (RouterProxy.HOME_SQUID, False, "HTTP 403"),
            (RouterProxy.MIZZOU_SQUID, True, None),
        ]

    def test_both_blocked_reports_both_and_returns_the_original(self):
        session = _Session([_Response(403), _Response(403)])
        d = _discovery(session)

        response = d._fetch_with_ssl_fallback("https://example.com/")

        assert response.status_code == 403
        assert [r[1] for r in d.reported] == [False, False]

    def test_alternate_transport_failure_does_not_raise(self):
        """The caller asked for a fetch; a bad second proxy must not turn a
        403 into an exception the old code never raised."""
        session = _Session(
            [_Response(403), requests.exceptions.ConnectionError("refused")]
        )
        d = _discovery(session)

        response = d._fetch_with_ssl_fallback("https://example.com/")

        assert response.status_code == 403
        assert d.reported[-1] == (RouterProxy.MIZZOU_SQUID, False, "refused")


class TestNoPointlessRetry:
    def test_no_retry_when_the_alternate_resolves_to_the_same_box(self):
        """MIZZOU_SQUID falls back onto home Squid when unconfigured, so the
        two names can resolve to one address -- retrying there would just
        re-ask the IP that was already refused."""
        manager = _ProxyManager({RouterProxy.MIZZOU_SQUID: HOME})
        session = _Session([_Response(403)])
        d = _discovery(session, manager=manager)

        d._fetch_with_ssl_fallback("https://example.com/")

        assert len(session.calls) == 1
        assert d.reported == [(RouterProxy.HOME_SQUID, False, "HTTP 403")]

    def test_no_retry_when_no_alternate_is_configured(self):
        manager = _ProxyManager({RouterProxy.HOME_SQUID: HOME})
        session = _Session([_Response(403)])
        d = _discovery(session, manager=manager)

        d._fetch_with_ssl_fallback("https://example.com/")

        assert len(session.calls) == 1

    def test_manager_without_the_resolver_degrades_quietly(self):
        """Test doubles built via __new__ may predate the resolver."""
        session = _Session([_Response(403)])
        d = _discovery(session, manager=types.SimpleNamespace())

        response = d._fetch_with_ssl_fallback("https://example.com/")

        assert response.status_code == 403
        assert len(session.calls) == 1
