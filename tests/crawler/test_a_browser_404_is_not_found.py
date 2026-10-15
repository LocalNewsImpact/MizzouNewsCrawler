"""A 404 the browser receives marks the link `404`, as an HTTP 404 does.

thenewstribune.com/news/local/article290216269.html answered HTTP 404 in the
browser and was served again every batch -- six times in five minutes on
2026-10-15 -- because only the HTTP path turned a 404 into NotFoundError.
"""

from __future__ import annotations

import inspect

from src.cli.commands import extraction
from src.crawler import ContentExtractor


def test_the_loop_raises_not_found_for_a_browser_404_with_no_story():
    flat = " ".join(inspect.getsource(extraction).split())
    assert 'nav_status = getattr(extractor, "_last_navigation_status", None)' in flat
    assert (
        'if nav_status in (404, 410) and not (content or {}).get("title"): '
        "raise NotFoundError("
    ) in flat


def test_it_is_checked_before_the_page_is_judged():
    source = inspect.getsource(extraction)
    check = source.index("if nav_status in (404, 410)")
    assert check < source.index(
        "# Check for proxy/bot challenge page before processing"
    )


def test_every_article_starts_with_no_browser_status():
    """An article fetched over HTTP must not read the last article's 404."""
    assert "self._last_navigation_status = None" in inspect.getsource(
        ContentExtractor.extract_content
    )


def test_a_mock_extractor_is_not_a_404():
    """`getattr` on a MagicMock returns a mock, which is not in (404, 410)."""
    from unittest.mock import MagicMock

    assert MagicMock()._last_navigation_status not in (404, 410)
