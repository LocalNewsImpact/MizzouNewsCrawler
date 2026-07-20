"""Tests for capture-once/parse-many reuse in the extraction fallback chain."""

import pytest

from src.crawler import ContentExtractor


@pytest.fixture
def extractor():
    """A bare extractor with just the capture-tracking state initialized."""
    ex = ContentExtractor.__new__(ContentExtractor)
    ex._raw_html_by_method = {}
    ex._latest_raw_html = None
    ex._latest_raw_html_method = None
    ex._last_bot_protection_detection = None
    return ex


def test_a_later_parser_reuses_an_earlier_fetch(extractor):
    """The whole point: don't fetch the same URL again to parse it again."""
    extractor._record_raw_html("<html>fetched once</html>", "mcmetadata")

    assert extractor._capture_for_parsing(None) == "<html>fetched once</html>"


def test_rendered_capture_beats_an_http_one(extractor):
    """Selenium's capture is the same page after JS — strictly more article."""
    extractor._record_raw_html("<html>http copy</html>", "mcmetadata")
    extractor._record_raw_html("<html>rendered copy</html>", "selenium")

    assert extractor._capture_for_parsing(None) == "<html>rendered copy</html>"
    # ...even when an earlier capture was already threaded through.
    assert extractor._capture_for_parsing("<html>http copy</html>") == (
        "<html>rendered copy</html>"
    )


def test_no_reuse_while_bot_protection_is_flagged(extractor):
    """The capture may be a challenge page; a fresh fetch is the escape hatch."""
    extractor._record_raw_html("<html>Just a moment...</html>", "mcmetadata")
    extractor._last_bot_protection_detection = {
        "type": "cloudflare",
        "status_code": 403,
        "source": "newspaper4k",
    }

    assert extractor._capture_for_parsing(None) is None


def test_prefetched_amp_capture_is_preserved(extractor):
    """A caller-supplied capture stands when nothing better was fetched."""
    assert extractor._capture_for_parsing("<html>amp</html>") == "<html>amp</html>"


def test_no_captures_yet_leaves_the_caller_unchanged(extractor):
    assert extractor._capture_for_parsing(None) is None


def test_kill_switch_restores_per_method_fetching(extractor, monkeypatch):
    """Reuse can be turned off in production without a rebuild."""
    monkeypatch.setenv("EXTRACTION_REUSE_CAPTURE", "false")
    extractor._record_raw_html("<html>fetched once</html>", "mcmetadata")

    assert extractor._capture_for_parsing(None) is None
    assert extractor._capture_for_parsing("<html>amp</html>") == "<html>amp</html>"


def test_most_recent_http_capture_wins_without_selenium(extractor):
    extractor._record_raw_html("<html>first</html>", "mcmetadata")
    extractor._record_raw_html("<html>second</html>", "newspaper4k")

    assert extractor._capture_for_parsing(None) == "<html>second</html>"
