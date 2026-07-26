"""Fetch-once-parse-many: one proxied fetcher, parser-only parsers.

The bug these tests pin against: mcmetadata (and newspaper4k via
article.download()) used to self-fetch with a bare requests.get -- no
proxy, no rotated UA -- egressing directly from the GKE pod IP (verified
empirically from a prod pod the week mcmetadata went live as primary).
No test caught it because every existing test either supplied html or
stubbed the extractor layer, so transport was never asserted.

The model (user-confirmed): the crawler's proxied per-domain session
(_fetch_page_html) and Selenium are the ONLY two things that ever egress.
mcmetadata / newspaper4k / BeautifulSoup are parsers -- they receive the
single capture and must never fetch.
"""

from unittest.mock import Mock

import pytest

import src.crawler as crawler_module
from src.crawler import ContentExtractor, NotFoundError, RateLimitError


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def extractor():
    """Bare extractor with just enough state for the fetch/parse layer."""
    ex = ContentExtractor.__new__(ContentExtractor)
    ex.timeout = 30
    ex.dead_url_ttl = 0
    ex.dead_urls = {}
    ex.domain_router_proxy = {}
    ex.domain_sessions = {}
    ex.domain_user_agents = {}
    ex.proxy_manager = Mock()
    ex.bot_sensitivity_manager = Mock()
    ex.mcmetadata_include_other_metadata = False
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


def _response(text="<html>page</html>", status=200, content_type="text/html"):
    response = Mock()
    response.status_code = status
    response.headers = {"content-type": content_type}
    response.encoding = "utf-8"
    response.apparent_encoding = "utf-8"
    response.text = text
    response.elapsed.total_seconds.return_value = 0.4
    return response


def _mc_result(**over):
    base = {
        "text_content": "Article body text. " * 20,
        "article_title": "Headline",
        "article_author": "Jane Reporter",
        "publication_date": None,
        "text_extraction_method": "trafilatura",
        "title_extraction_method": "mcmetadata",
        "author_extraction_method": None,
        "normalized_url": "example.com/story",
        "canonical_url": "https://example.com/story",
        "language": "en",
    }
    base.update(over)
    return base


class TestFetchPageHtml:
    """_fetch_page_html is the single proxied HTTP capture step."""

    def test_fetches_through_domain_session(self, extractor):
        session = Mock()
        session.proxies = {"https": "http://user:pw@squid.example:3128"}
        session.get.return_value = _response()
        extractor._get_domain_session = Mock(return_value=session)

        html = extractor._fetch_page_html("https://example.com/story")

        extractor._get_domain_session.assert_called_once_with(
            "https://example.com/story"
        )
        args, kwargs = session.get.call_args
        assert args[0] == "https://example.com/story"
        assert kwargs["timeout"] == 30
        assert html == "<html>page</html>"

    def test_success_reports_to_router_and_records_telemetry(self, extractor):
        session = Mock()
        session.proxies = {"https": "http://user:pw@squid.example:3128"}
        session.get.return_value = _response()
        extractor._get_domain_session = Mock(return_value=session)

        extractor._fetch_page_html("https://example.com/story")

        args, kwargs = extractor.proxy_manager.report_domain_result.call_args
        assert args[0] == "example.com"
        assert kwargs["success"] is True
        meta = extractor._last_fetch_proxy_metadata
        assert meta["proxy_used"] is True
        assert "pw" not in (meta["proxy_url"] or "")  # credentials masked
        assert extractor._last_fetch_http_status == 200

    def test_404_raises_not_found(self, extractor):
        session = Mock()
        session.proxies = {}
        session.get.return_value = _response(status=404)
        extractor._get_domain_session = Mock(return_value=session)

        with pytest.raises(NotFoundError):
            extractor._fetch_page_html("https://example.com/gone")

    def test_500_raises_rate_limit_with_backoff(self, extractor):
        backoffs = []
        extractor._handle_rate_limit_error = lambda domain, resp=None: backoffs.append(
            domain
        )
        session = Mock()
        session.proxies = {}
        session.get.return_value = _response(status=500)
        extractor._get_domain_session = Mock(return_value=session)

        with pytest.raises(RateLimitError):
            extractor._fetch_page_html("https://example.com/story")

        assert backoffs == ["example.com"]

    def test_connection_error_reports_failure_and_reraises(self, extractor):
        session = Mock()
        session.proxies = {}
        session.get.side_effect = ConnectionError("proxy unreachable")
        extractor._get_domain_session = Mock(return_value=session)

        with pytest.raises(ConnectionError):
            extractor._fetch_page_html("https://example.com/story")

        args, kwargs = extractor.proxy_manager.report_domain_result.call_args
        assert kwargs["success"] is False

    def test_bot_protection_raises_generic_for_selenium_fallback(self, extractor):
        extractor._detect_bot_protection_in_response = lambda r: "cloudflare"
        session = Mock()
        session.proxies = {}
        session.get.return_value = _response(status=403)
        extractor._get_domain_session = Mock(return_value=session)

        with pytest.raises(Exception, match="Bot protection"):
            extractor._fetch_page_html("https://example.com/story")


class TestParsersNeverFetch:
    """Parsers receive the capture; none of them may touch the network."""

    def test_parse_with_mcmetadata_requires_html(self, extractor):
        """THE invariant: no html means an error, never a self-fetch via
        mcmetadata.extract(url, html_text=None)."""
        with pytest.raises(RuntimeError, match="requires HTML"):
            extractor._parse_with_mcmetadata("https://example.com/story", None)

    def test_parse_with_mcmetadata_passes_html_through(
        self, extractor, monkeypatch
    ) -> None:
        captured = {}

        def fake_extract(**kwargs):
            captured.update(kwargs)
            return _mc_result()

        monkeypatch.setattr(crawler_module.mcmetadata, "extract", fake_extract)

        result = extractor._parse_with_mcmetadata(
            "https://example.com/story", "<html>capture</html>"
        )

        assert captured["html_text"] == "<html>capture</html>"
        assert result["title"] == "Headline"

    def test_parse_with_newspaper_without_html_is_error_result(self, extractor):
        result = extractor._parse_with_newspaper("https://example.com/story")

        assert result["success"] is False
        assert "without html" in result["error"]

    def test_parse_with_beautifulsoup_without_html_returns_empty(self, extractor):
        assert extractor._parse_with_beautifulsoup("https://example.com/story") == {}
