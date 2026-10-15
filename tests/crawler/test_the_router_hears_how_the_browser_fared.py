"""The router hears how the proxy it chose for the browser fared.

The auth relay asks the router which Squid serves each browser connection
(since #429), and nothing on the browser path ever reported back -- none of
the `report_domain_result` calls is in `_extract_with_selenium`. So a proxy
Cloudflare refused for a host was never backed off for it, and the router
kept sending the browser there: myedmondsnews.com, 2026-10-14, every browser
navigation went through the Mizzou Squid, was held at "Just a moment..." and
ended HTTP 403, and the router's record for that pair still showed one
failure, from September.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from src.crawler import ContentExtractor, proxy_relay
from src.crawler.proxy_router import RouterProxy

URL = "https://myedmondsnews.com/2025/03/hygiene-center/"


@pytest.fixture(autouse=True)
def no_routes(monkeypatch):
    monkeypatch.setattr(proxy_relay, "_routes", {})


class TestTheRelayRemembersItsRoute:
    def test_the_routers_choice_is_kept_per_host(self, monkeypatch):
        manager = MagicMock()
        manager.get_requests_proxies_for_domain.return_value = (
            {"https": "http://u:p@mizzou:3128"},
            RouterProxy.MIZZOU_SQUID,
            "http",
        )
        monkeypatch.setattr(
            "src.crawler.proxy_config.get_proxy_manager", lambda: manager
        )
        assert proxy_relay._router_upstream("MyEdmondsNews.com") == (
            "http://u:p@mizzou:3128"
        )
        assert proxy_relay.routed_proxy_for("myedmondsnews.com") is (
            RouterProxy.MIZZOU_SQUID
        )

    def test_a_host_never_routed_has_no_route(self):
        assert proxy_relay.routed_proxy_for("example.com") is None


def _extractor():
    extractor = ContentExtractor.__new__(ContentExtractor)
    extractor.proxy_manager = MagicMock()
    return extractor


def _reports(extractor):
    return [
        (c.args[0], c.args[1], c.kwargs["success"])
        for c in extractor.proxy_manager.report_domain_result.call_args_list
    ]


class TestTheOutcomeIsReported:
    @pytest.mark.parametrize("status", [403, 429, 503])
    def test_a_refusal_is_a_failure_of_the_routed_proxy(self, status):
        proxy_relay._routes["myedmondsnews.com"] = RouterProxy.MIZZOU_SQUID
        extractor = _extractor()
        extractor._report_browser_route(URL, status)
        assert _reports(extractor) == [
            ("myedmondsnews.com", RouterProxy.MIZZOU_SQUID, False)
        ]

    def test_a_page_is_a_success(self):
        proxy_relay._routes["myedmondsnews.com"] = RouterProxy.HOME_SQUID
        extractor = _extractor()
        extractor._report_browser_route(URL, 200)
        assert _reports(extractor) == [
            ("myedmondsnews.com", RouterProxy.HOME_SQUID, True)
        ]

    @pytest.mark.parametrize("status", [404, 410, None])
    def test_a_missing_page_or_no_status_says_nothing_about_the_proxy(self, status):
        proxy_relay._routes["myedmondsnews.com"] = RouterProxy.MIZZOU_SQUID
        extractor = _extractor()
        extractor._report_browser_route(URL, status)
        assert _reports(extractor) == []

    def test_an_unrouted_host_reports_nothing(self):
        extractor = _extractor()
        extractor._report_browser_route(URL, 403)
        assert _reports(extractor) == []

    def test_the_browser_path_reports_after_reading_the_status(self):
        source = inspect.getsource(ContentExtractor._extract_with_selenium)
        read = source.index("read_navigation_status(driver)")
        assert read < source.index("self._report_browser_route(url, nav_status)")
