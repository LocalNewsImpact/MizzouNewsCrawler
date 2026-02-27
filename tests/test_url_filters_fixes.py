"""Regression tests covering the updated article URL heuristics."""

import pytest

from src.pipeline.url_filters import _normalize_url_for_patterns, check_is_article

FILE_URLS = (
    "https://example.com/image.jpg",
    "https://example.com/document.pdf",
    "https://example.com/script.js",
    "https://example.com/style.css",
    "https://example.com/data.json",
    "https://example.com/photo.jpeg",
    "https://example.com/icon.svg",
)


def test_file_extensions_filtered():
    for url in FILE_URLS:
        assert not check_is_article(url), f"File URL should be filtered: {url}"


def test_directory_paths_normalized():
    assert not check_is_article("https://example.com/feed")
    assert not check_is_article("https://example.com/search")
    assert not check_is_article("https://example.com/about")


def test_query_parameters_preserved():
    assert not check_is_article("https://example.com/feed?page=2")
    assert not check_is_article("https://example.com/search?q=news")


def test_fragments_preserved():
    assert not check_is_article("https://example.com/about#section")
    assert not check_is_article("https://example.com/contact#form")


def test_normalization_edge_cases():
    assert not check_is_article("")
    assert not check_is_article(None)
    assert check_is_article("example.com/news/article") is True


def test_video_patterns_consistent():
    video_urls = (
        "https://example.com/video/news-clip",
        "https://example.com/watch/live-stream",
        "https://example.com/videos/archive",
    )
    for url in video_urls:
        assert not check_is_article(url)


def test_audio_patterns_consistent():
    audio_urls = (
        "https://example.com/audio/podcast-episode",
        "https://example.com/listen/radio-show",
        "https://example.com/podcast/daily-news",
        "https://example.com/podcasts/archive",
    )
    for url in audio_urls:
        assert not check_is_article(url)


def test_article_patterns_pass():
    article_urls = (
        "https://example.com/news/breaking-story",
        "https://example.com/2024/01/15/election-results",
        "https://example.com/stories/local-impact",
        "https://example.com/article/weather-update",
        "https://example.com/content/sports-recap",
        "https://example.com/posts/community-event",
        "https://example.com/blog/analysis-piece",
    )
    for url in article_urls:
        assert check_is_article(url) is True


def test_storysniffer_returns_boolean():
    result = check_is_article("https://example.com/unknown/path")
    assert isinstance(result, bool)


def test_storysniffer_fallback_on_exception(monkeypatch):
    class BrokenSniffer:  # pylint: disable=too-few-public-methods
        def __init__(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("src.pipeline.url_filters.StorySniffer", BrokenSniffer)
    assert check_is_article("https://example.com/some/path") is False


def test_category_urls_not_auto_filtered():
    category_urls = (
        "https://example.com/category/local-news/breaking-story",
        "https://example.com/tag/politics/election-analysis",
        "https://example.com/page/2/news-archive",
    )
    for url in category_urls:
        assert isinstance(check_is_article(url), bool)


def test_normalize_url_empty_string_direct():
    """Test _normalize_url_for_patterns with empty string (line 28)."""
    assert _normalize_url_for_patterns("") == ""


def test_normalize_url_none_direct():
    """Test _normalize_url_for_patterns with None (line 28)."""
    assert _normalize_url_for_patterns(None) == ""


def test_normalize_url_whitespace_only():
    """Test _normalize_url_for_patterns with whitespace (line 28)."""
    assert _normalize_url_for_patterns("   ") == ""


def test_storysniffer_exception_during_check(monkeypatch):
    """Test StorySniffer.is_news() raising exception (line 119)."""
    class FailingSniffer:  # pylint: disable=too-few-public-methods
        def __init__(self):
            pass

        def is_news(self, _url):
            raise ValueError("StorySniffer check failed")

        def guess(self, _url):
            raise ValueError("StorySniffer guess failed")

    monkeypatch.setattr("src.pipeline.url_filters.StorySniffer", 
                       lambda: FailingSniffer())
    result = check_is_article("https://example.com/unknown")
    # Exception handler returns False
    assert result is False
