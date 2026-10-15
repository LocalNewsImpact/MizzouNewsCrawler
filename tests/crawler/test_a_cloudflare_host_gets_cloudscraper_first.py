"""A Cloudflare host gets cloudscraper before the browser, as its plan says.

myedmondsnews.com, probed from a production pod on 2026-10-14:

    path          requests   cloudscraper   browser (article)
    residential   403        200 (story)    "Just a moment..." for 61s
    mizzou        403        403            "Just a moment..." for 62s

The fetch plan for a `selenium` + `cloudflare` host said "cloudscraper before
selenium" and `extract_content` only logged it: the browser still went first,
so cloudscraper was never tried. Which proxy it goes through is the router's
existing failover, not this test's concern.
"""

from __future__ import annotations

import pytest

import src.crawler as crawler_module
from src.crawler import ContentExtractor

URL = "https://myedmondsnews.com/2025/03/hygiene-center-celebrating-5-year/"
STORY = """<html><head><title>Hygiene Center celebrating 5-year anniversary</title>
</head><body><article><h1>Hygiene Center celebrating 5-year anniversary</h1>
<p>The Lynnwood hygiene center marks five years of free showers and laundry for
people experiencing homelessness with an open house on April 8.</p>
<p>Staff said the center served more than 4,000 visits last year, and that a
new washer and dryer donated by a local church will double its laundry
capacity before summer.</p></article></body></html>"""


@pytest.fixture
def cloudflare_selenium_host(monkeypatch):
    """`selenium` + `cloudflare`, cloudscraper installed, Selenium available.

    Both flags pinned: they differ between dev and CI.
    """
    monkeypatch.setattr(crawler_module, "SELENIUM_AVAILABLE", True)
    monkeypatch.setattr(crawler_module, "CLOUDSCRAPER_AVAILABLE", True)
    extractor = ContentExtractor()
    monkeypatch.setattr(extractor, "_requires_login", lambda host: False)
    monkeypatch.setattr(
        extractor,
        "_get_domain_extraction_method",
        lambda domain: ("selenium", "cloudflare"),
    )
    monkeypatch.setattr(extractor, "_get_domain_amp_support", lambda d: None)
    monkeypatch.setattr(extractor, "get_persistent_driver", lambda: None)
    order: list[str] = []

    def fetch(url, metrics=None):
        order.append("http")
        return STORY

    def selenium(url, result, metrics, reason, **_kwargs):
        order.append("selenium")
        return True, False

    monkeypatch.setattr(extractor, "_fetch_page_html", fetch)
    monkeypatch.setattr(extractor, "_run_selenium_extraction", selenium)
    return extractor, order


class TestCloudscraperGoesFirst:
    def test_the_http_capture_comes_before_the_browser(self, cloudflare_selenium_host):
        extractor, order = cloudflare_selenium_host
        extractor._get_domain_selenium_only = lambda domain: False
        result = extractor.extract_content(URL)
        assert order[0] == "http"
        assert "4,000 visits" in (result["content"] or "")

    def test_a_selenium_only_host_still_goes_to_the_browser(
        self, cloudflare_selenium_host
    ):
        """`selenium_only` says no HTTP of any kind; the plan honours it."""
        extractor, order = cloudflare_selenium_host
        extractor._get_domain_selenium_only = lambda domain: True
        extractor.extract_content(URL)
        assert order[0] == "selenium"
        assert "http" not in order
