"""The row says which Squid the page came through, and whether it was blurred.

69 WSU stories were stored as the paywall's blurred text while
`authenticated_session` said true: the login had run and the page did not
honour it. Nothing said which egress the page came through -- telemetry logged
the relay's fallback Squid for every browser fetch, with `router_proxy` empty --
so "was it the IP?" had no answer.
"""

from __future__ import annotations

import inspect

import pytest

from src.crawler import ContentExtractor, proxy_relay
from src.crawler.proxy_relay import PublisherRoute
from src.crawler.proxy_router import RouterProxy
from src.utils.blurry_text import is_blurred


@pytest.fixture
def route(monkeypatch):
    fresh = PublisherRoute()
    monkeypatch.setattr(proxy_relay, "_browser_route", fresh)
    monkeypatch.setattr(proxy_relay, "_routes", {})
    return fresh


class TestWhichSquid:
    def test_a_browser_page_records_the_relays_route_for_its_publisher(self, route):
        e = ContentExtractor()
        e._raw_html_by_method = {"selenium": "<html></html>"}
        proxy_relay._routes["yakimaherald.com"] = RouterProxy.MIZZOU_SQUID
        route.upstream_for(
            "yakimaherald.com", lambda k: "http://u:secret@10.0.0.9:3128"
        )
        got = e._proxy_used("https://www.yakimaherald.com/news/a.html")
        assert got["router_proxy"] == "mizzou_squid"
        assert got["path"] == "browser"
        assert "secret" not in (got["proxy_url"] or "")
        assert "10.0.0.9:3128" in got["proxy_url"]

    def test_a_plain_fetch_records_its_sessions_router_choice(self, route):
        e = ContentExtractor()
        e._raw_html_by_method = {"http": "<html></html>"}
        e.domain_router_proxy["www.example.com"] = RouterProxy.HOME_SQUID
        assert e._proxy_used("https://www.example.com/x") == {
            "router_proxy": "home_squid",
            "path": "http",
        }

    def test_nothing_recorded_is_none_not_a_guess(self, route):
        e = ContentExtractor()
        e._raw_html_by_method = {}
        assert e._proxy_used("https://www.example.com/x") is None


class TestWhatThePageServed:
    @pytest.mark.parametrize(
        "html, want",
        [
            ('<p class="mark-text">a <span class="blurry-text">wjfx</span></p>', True),
            ("<p class='blurry-text'>uif</p>", True),
            ("<p>plain</p><style>.blurry-text{}</style>", False),
            (None, False),
            ("", False),
        ],
    )
    def test_a_blurred_page_is_said_to_be_one(self, html, want):
        assert is_blurred(html) is want


def test_every_live_extraction_stamps_both_and_a_replay_neither():
    source = inspect.getsource(ContentExtractor.extract_content)
    stamp = source[source.index("proxy = self._proxy_used(url)") - 120 :][:900]
    assert "if not replay:" in stamp
    assert 'result_copy["metadata"]["proxy"] = proxy' in stamp
    assert 'result_copy["metadata"]["paywall_blurred"] = is_blurred(' in stamp
    assert "metrics.router_proxy = proxy" in stamp
