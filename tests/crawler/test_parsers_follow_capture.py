"""Selenium captures; the real parsers read that capture.

Selenium renders HTML, but on the http_fallback path only its own generic soup
extraction ever read the render — so after paying minutes for a browser the
article came from the weaker parser. trafilatura now parses the capture, and
Selenium's own result fills only what is left.

The two halves are inseparable: the merge previously overwrote
title/author/content/metadata unconditionally, which would undo the capture
parse immediately.
"""

import pytest

from src.crawler import ContentExtractor

TRAFILATURA_BODY = "Body text as trafilatura reads the rendered page. " * 6
SOUP_BODY = "Weaker soup extraction of the same rendered page. " * 6
HTTP_BODY = "Body text an HTTP parser already got. " * 6


@pytest.fixture
def extractor(monkeypatch):
    monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True, raising=False)
    ex = ContentExtractor.__new__(ContentExtractor)
    ex._selenium_failure_counts = {}
    ex._last_bot_protection_detection = None
    ex._publish_date_details = None
    ex._check_rate_limit = lambda dom: False
    ex._mcmetadata_enabled = lambda: True
    ex._raw_html_by_method = {"selenium": "<html>rendered</html>"}
    ex._extract_with_selenium = lambda url: {
        "title": "Headline from soup",
        "author": "Jane Reporter",
        "content": SOUP_BODY,
        "metadata": {"page_source_length": 1234, "meta_description": "d"},
    }
    return ex


def _result(**over):
    base = {
        "url": "https://example.com/story",
        "title": None,
        "author": None,
        "publish_date": None,
        "content": None,
        "metadata": {},
        "extraction_methods": {},
    }
    base.update(over)
    return base


def test_capture_is_parsed_by_trafilatura_not_only_soup(extractor):
    """The point: the better parser reads the rendered page."""
    extractor._extract_with_mcmetadata = lambda url, html=None, **kw: {
        "title": "Headline from trafilatura",
        "content": TRAFILATURA_BODY,
        "publish_date": "2026-07-20",
        "metadata": {"meta_description": "from mcmetadata"},
    }
    result = _result()

    extractor._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["content"]
    )

    assert result["content"] == TRAFILATURA_BODY
    assert result["extraction_methods"]["content"] == "mcmetadata"


def test_soup_fills_only_what_trafilatura_left(extractor):
    """Selenium's own extraction is the last resort, not the default."""
    extractor._extract_with_mcmetadata = lambda url, html=None, **kw: {
        "content": TRAFILATURA_BODY,
        "metadata": {"meta_description": "d"},
    }
    result = _result()

    extractor._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["content"]
    )

    assert result["content"] == TRAFILATURA_BODY  # trafilatura kept
    assert result["author"] == "Jane Reporter"  # gap filled by soup
    assert result["extraction_methods"]["author"] == "selenium"


def test_good_http_content_survives_an_author_only_escalation(extractor):
    """Escalating for a byline must not discard body text already extracted."""
    extractor._extract_with_mcmetadata = lambda url, html=None, **kw: {}
    result = _result(
        title="Good HTTP headline",
        content=HTTP_BODY,
        publish_date="2026-07-20",
        metadata={"meta_description": "d"},
        extraction_methods={"content": "mcmetadata", "title": "mcmetadata"},
    )

    extractor._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["author"]
    )

    assert result["content"] == HTTP_BODY
    assert result["title"] == "Good HTTP headline"
    assert result["extraction_methods"]["content"] == "mcmetadata"
    assert result["author"] == "Jane Reporter"


def test_bot_blocked_http_fields_are_replaced_by_the_capture_parse(extractor):
    """Challenge-page text is not worth preserving."""
    extractor._last_bot_protection_detection = {"type": "cloudflare"}
    extractor._extract_with_mcmetadata = lambda url, html=None, **kw: {
        "title": "Real headline",
        "content": TRAFILATURA_BODY,
        "metadata": {"meta_description": "d"},
    }
    result = _result(
        title="Just a moment...",
        content="Checking your browser before accessing the site. " * 3,
        metadata={"meta_description": "d"},
        extraction_methods={"content": "newspaper4k"},
    )

    extractor._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["author"]
    )

    assert result["content"] == TRAFILATURA_BODY
    assert result["title"] == "Real headline"


def test_capture_parse_failure_falls_back_to_soup(extractor):
    """A parser blowing up must not strand the article."""

    def boom(url, html=None, **kw):
        raise RuntimeError("trafilatura exploded")

    extractor._extract_with_mcmetadata = boom
    result = _result()

    extractor._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["content"]
    )

    assert result["content"] == SOUP_BODY


def test_no_capture_recorded_still_works(extractor):
    extractor._raw_html_by_method = {}
    extractor._extract_with_mcmetadata = lambda url, html=None, **kw: {
        "content": "should not be used"
    }
    result = _result()

    extractor._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["content"]
    )

    assert result["content"] == SOUP_BODY
