"""The browser leaves a page once it has read it.

`window.stop()` stops loading, not running. A subscriber page's scripts kept
running after the capture and held the renderer, so the next command waited
out the 30s client timeout and the driver was replaced: tri-cityherald.com
logged in, 2026-10-14, three driver replacements in fifteen minutes and ten
failed articles. Left for about:blank, three articles in a row loaded in
1.1-1.7s.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from src.crawler import ContentExtractor


def test_it_unloads_the_page():
    driver = MagicMock()
    ContentExtractor._leave_page(driver)
    driver.get.assert_called_once_with("about:blank")


def test_a_browser_that_will_not_answer_is_left_to_the_next_navigation():
    driver = MagicMock()
    driver.get.side_effect = RuntimeError("Read timed out")
    ContentExtractor._leave_page(driver)  # does not raise


def test_it_runs_after_the_session_check_and_before_the_return():
    """`get_cookies()` reads only the current document's origin, so the
    session check must see the article's page, not about:blank."""
    source = inspect.getsource(ContentExtractor._extract_with_selenium)
    confirm = source.index("self._confirm_session(driver, url)")
    leave = source.index("self._leave_page(driver)")
    assert confirm < leave < source.index("return result", leave)
