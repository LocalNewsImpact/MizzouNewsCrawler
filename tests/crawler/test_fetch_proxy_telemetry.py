"""Proxy/router telemetry must survive the fetch, on every parser path.

Two independent defects nulled these columns in production simultaneously
(confirmed live 2026-07-27 over 3,150 rows in 6h):

1. ``set_proxy_metrics`` assigned ``proxy_status`` -- via
   ``proxy_status_to_int`` -- BEFORE ``router_proxy``. The fetch path passed
   the int HTTP status (200), ``status.lower()`` raised AttributeError, and
   the exception escaped the method with proxy_used/proxy_url already set but
   router_proxy never assigned. Result: router_proxy NULL on 100% of rows and
   proxy_status NULL on 100% of rows, while proxy_url looked perfectly fine --
   which is exactly why it read as "routing is broken" rather than
   "telemetry is broken".

2. ``_fetch_page_html`` recorded the proxy metadata only onto
   ``self._last_fetch_proxy_metadata``, whose sole reader is
   ``_parse_with_newspaper``. Whenever newspaper4k did not run -- the common
   case -- proxy_used/proxy_url/router_proxy never reached telemetry at all.
   2,621 of 3,150 rows reported proxy_used=0 with a perfect correlation to
   newspaper4k not running, though every one of those fetches went through
   Squid. The proxy was never bypassed; the evidence was.

Both paths are covered here, in both the proxied and un-proxied states, so a
regression on either cannot pass as green again.
"""

from unittest.mock import Mock

import pytest

from src.crawler import ContentExtractor
from src.crawler.proxy_config import RouterProxy
from src.utils.comprehensive_telemetry import (
    PROXY_STATUS_SUCCESS,
    ExtractionMetrics,
    proxy_status_to_int,
)


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def extractor():
    """Bare extractor with just enough state for the fetch layer."""
    ex = ContentExtractor.__new__(ContentExtractor)
    ex.timeout = 30
    ex.dead_url_ttl = 0
    ex.dead_urls = {}
    ex.domain_router_proxy = {}
    ex.domain_sessions = {}
    ex.domain_user_agents = {}
    ex.proxy_manager = Mock()
    ex.bot_sensitivity_manager = Mock()
    ex._latest_wire_hints = None
    ex._last_bot_protection_detection = None
    ex._update_wire_hints_from_html = lambda *a, **k: None
    ex._record_raw_html = lambda *a, **k: None
    ex._check_rate_limit = lambda domain: False
    ex._get_domain_lock = lambda domain: _NullLock()
    ex._generate_referer = lambda url: None
    ex._get_domain_amp_support = lambda domain: None
    ex._reset_error_count = lambda domain: None
    ex._handle_rate_limit_error = lambda *a, **k: None
    ex._handle_connection_error_with_proxy_escalation = lambda *a, **k: None
    ex._detect_bot_protection_in_response = lambda response: None
    ex._record_bot_protection_detection = lambda *a, **k: None
    return ex


def _response(text="<html>page</html>", status=200):
    response = Mock()
    response.status_code = status
    response.headers = {"content-type": "text/html"}
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.text = text
    response.elapsed.total_seconds.return_value = 0.4
    return response


def _metrics():
    return ExtractionMetrics(
        "op-1", "article-1", "https://example.com/s", "example.com"
    )


class TestProxyStatusCoercion:
    """proxy_status_to_int must never raise -- it runs inside telemetry."""

    def test_int_status_returns_none_instead_of_raising(self):
        # The exact production input. Used to raise AttributeError.
        assert proxy_status_to_int(200) is None

    def test_none_status_returns_none(self):
        assert proxy_status_to_int(None) is None

    def test_known_words_still_map(self):
        assert proxy_status_to_int("success") == PROXY_STATUS_SUCCESS
        assert proxy_status_to_int("SUCCESS") == PROXY_STATUS_SUCCESS

    def test_unknown_word_returns_none(self):
        assert proxy_status_to_int("nonsense") is None


class TestSetProxyMetricsOrdering:
    """router_proxy must not depend on the status coercion succeeding."""

    def test_router_proxy_survives_bad_status_type(self):
        metrics = _metrics()
        # Shape of the call that used to silently drop router_proxy.
        metrics.set_proxy_metrics(
            proxy_used=True,
            proxy_url="http://squid.example:3128",
            proxy_authenticated=True,
            proxy_status=200,
            router_proxy="mizzou_squid",
        )
        assert metrics.router_proxy == "mizzou_squid"
        assert metrics.proxy_used is True
        assert metrics.proxy_url == "http://squid.example:3128"

    def test_status_word_recorded_when_well_formed(self):
        metrics = _metrics()
        metrics.set_proxy_metrics(
            proxy_used=True,
            proxy_url="http://squid.example:3128",
            proxy_status="success",
            router_proxy="home_squid",
        )
        assert metrics.proxy_status == PROXY_STATUS_SUCCESS
        assert metrics.router_proxy == "home_squid"


class TestFetchRecordsProxyTelemetry:
    """The fetch step itself must report proxy/router onto the metrics object.

    Previously this only reached telemetry through _parse_with_newspaper, so
    these assertions fail on the pre-fix code even though the fetch was
    correctly proxied.
    """

    def test_records_router_proxy_without_any_parser_running(self, extractor):
        session = Mock()
        session.proxies = {"https": "http://user:pw@squid.example:3128"}
        session.get.return_value = _response()
        extractor._get_domain_session = lambda url: session
        extractor.domain_router_proxy["example.com"] = RouterProxy.MIZZOU_SQUID

        metrics = _metrics()
        extractor._fetch_page_html("https://example.com/story", metrics=metrics)

        # No parser has run at this point -- this is the fetch step alone.
        assert metrics.router_proxy == RouterProxy.MIZZOU_SQUID.value
        assert metrics.proxy_used is True
        assert metrics.proxy_status == PROXY_STATUS_SUCCESS
        assert "squid.example" in (metrics.proxy_url or "")

    def test_credentials_are_masked_in_recorded_url(self, extractor):
        session = Mock()
        session.proxies = {"https": "http://user:sekret@squid.example:3128"}
        session.get.return_value = _response()
        extractor._get_domain_session = lambda url: session
        extractor.domain_router_proxy["example.com"] = RouterProxy.HOME_SQUID

        metrics = _metrics()
        extractor._fetch_page_html("https://example.com/story", metrics=metrics)

        assert "sekret" not in (metrics.proxy_url or "")
        assert metrics.proxy_authenticated is True

    def test_unproxied_session_records_no_proxy_and_no_status(self, extractor):
        """The other state: a session without proxies must not claim one."""
        session = Mock()
        session.proxies = {}
        session.get.return_value = _response()
        extractor._get_domain_session = lambda url: session

        metrics = _metrics()
        extractor._fetch_page_html("https://example.com/story", metrics=metrics)

        assert metrics.proxy_used is False
        assert metrics.proxy_url is None
        # No proxy was used, so there is no proxy status to report.
        assert metrics.proxy_status is None
        assert metrics.router_proxy is None

    def test_router_proxy_absent_when_router_made_no_choice(self, extractor):
        """Proxied by the static fallback, but the router never assigned one."""
        session = Mock()
        session.proxies = {"https": "http://squid.example:3128"}
        session.get.return_value = _response()
        extractor._get_domain_session = lambda url: session
        # domain_router_proxy deliberately left empty for this domain.

        metrics = _metrics()
        extractor._fetch_page_html("https://example.com/story", metrics=metrics)

        assert metrics.proxy_used is True
        assert metrics.router_proxy is None

    def test_fetch_still_returns_html_if_metrics_recording_breaks(self, extractor):
        """Telemetry must never be able to discard a capture we already hold."""
        session = Mock()
        session.proxies = {"https": "http://squid.example:3128"}
        session.get.return_value = _response(text="<html>body</html>")
        extractor._get_domain_session = lambda url: session

        metrics = Mock()
        metrics.set_proxy_metrics.side_effect = RuntimeError("telemetry down")

        html = extractor._fetch_page_html("https://example.com/story", metrics=metrics)
        assert "body" in html
