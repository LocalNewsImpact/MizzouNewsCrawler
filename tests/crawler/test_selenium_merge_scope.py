"""Selenium must fill the gaps it was called for, not replace good extractions.

Selenium escalates when a field is missing. It used to overwrite
title/content/metadata on every run regardless, so an escalation over a missing
byline also discarded body text that mcmetadata/trafilatura had already
extracted — replacing a purpose-built extractor's output with a generic soup
fallback, and misattributing the result in telemetry.
"""

import pytest

from src.crawler import ContentExtractor

GOOD_CONTENT = "Real article body extracted by trafilatura. " * 6
SELENIUM_CONTENT = "Weaker soup-based body text from the browser fallback. " * 6


@pytest.fixture
def extractor(monkeypatch):
    monkeypatch.setattr("src.crawler.SELENIUM_AVAILABLE", True, raising=False)
    ex = ContentExtractor.__new__(ContentExtractor)
    ex._selenium_failure_counts = {}
    ex._last_bot_protection_detection = None
    ex._check_rate_limit = lambda dom: False
    ex._publish_date_details = None
    return ex


def _result_missing_author():
    """What the chain looks like when only the byline is missing."""
    return {
        "url": "https://example.com/story",
        "title": "A perfectly good headline",
        "author": None,
        "publish_date": "2026-07-20",
        "content": GOOD_CONTENT,
        "metadata": {"meta_description": "from mcmetadata"},
        "extraction_methods": {
            "title": "mcmetadata",
            "content": "mcmetadata",
            "publish_date": "mcmetadata",
        },
    }


def _selenium_result():
    return {
        "url": "https://example.com/story",
        "title": "Headline as the browser saw it",
        "author": "Jane Reporter",
        "content": SELENIUM_CONTENT,
        "metadata": {"page_source_length": 12345, "stealth_method": "undetected"},
    }


def test_author_only_escalation_keeps_the_good_content(extractor):
    """The whole point: don't trade trafilatura's body for the soup fallback."""
    ex = extractor
    ex._extract_with_selenium = lambda url: _selenium_result()
    result = _result_missing_author()

    attempted, success = ex._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["author"]
    )

    assert (attempted, success) == (True, True)
    assert result["author"] == "Jane Reporter"  # the gap is filled
    assert result["content"] == GOOD_CONTENT  # ...and nothing else moved
    assert result["title"] == "A perfectly good headline"
    assert result["extraction_methods"]["content"] == "mcmetadata"
    assert result["extraction_methods"]["author"] == "selenium"


def test_bot_protection_still_overwrites(extractor):
    """Fields off a challenge page are not worth preserving."""
    ex = extractor
    ex._extract_with_selenium = lambda url: _selenium_result()
    ex._last_bot_protection_detection = {"type": "cloudflare", "source": "newspaper4k"}

    result = _result_missing_author()
    result["title"] = "Just a moment..."
    result["content"] = "Checking your browser before accessing the site. " * 3

    ex._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["author"]
    )

    assert result["content"] == SELENIUM_CONTENT
    assert result["title"] == "Headline as the browser saw it"
    assert result["extraction_methods"]["content"] == "selenium"


def test_flag_on_the_result_also_counts_as_suspect(extractor):
    ex = extractor
    ex._extract_with_selenium = lambda url: _selenium_result()
    result = _result_missing_author()
    result["_bot_protection_detected"] = True

    ex._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["author"]
    )

    assert result["content"] == SELENIUM_CONTENT


def test_selenium_diagnostics_survive_without_clobbering_metadata(extractor):
    """Why the browser ran is still recorded, but earlier metadata stands."""
    ex = extractor
    ex._extract_with_selenium = lambda url: _selenium_result()
    result = _result_missing_author()

    ex._run_selenium_extraction(
        "https://example.com/story", result, None, "http_fallback", ["author"]
    )

    assert result["metadata"]["meta_description"] == "from mcmetadata"
    assert result["metadata"]["selenium_reason"] == "http_fallback"
    assert result["metadata"]["page_source_length"] == 12345


def test_missing_content_is_still_filled(extractor):
    """When content genuinely is absent, Selenium supplies it."""
    ex = extractor
    ex._extract_with_selenium = lambda url: _selenium_result()
    result = _result_missing_author()
    result["content"] = None
    result["extraction_methods"].pop("content")

    ex._run_selenium_extraction(
        "https://example.com/story",
        result,
        None,
        "http_fallback",
        ["author", "content"],
    )

    assert result["content"] == SELENIUM_CONTENT
    assert result["extraction_methods"]["content"] == "selenium"
