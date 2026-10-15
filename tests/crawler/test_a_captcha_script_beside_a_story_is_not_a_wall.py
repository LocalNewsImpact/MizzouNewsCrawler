"""A captcha script beside a readable story is not a wall, and checks do not wait.

myedmondsnews.com, 2026-10-14: one article took nine minutes. The page ships a
Turnstile/reCAPTCHA script beside a readable story; the keyword branch of
`_detect_captcha_or_challenge` called that a challenge, and the crawler made
four failed "bypass" attempts. Each check took 50s on its own: ten selectors
that are normally absent, each waiting out the driver's 5s implicit wait. The
modal and paywall helpers after it spent another four minutes the same way.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.crawler import ContentExtractor, without_implicit_wait


class FakeDriver:
    def __init__(self, page_source: str = ""):
        self.page_source = page_source
        self.waits: list[float] = []
        self.timeouts = SimpleNamespace(implicit_wait=5)

    def implicitly_wait(self, seconds):
        self.waits.append(seconds)
        self.timeouts.implicit_wait = seconds

    def find_elements(self, *_args):
        return []


class TestTheWaitIsOffDuringAChecks:
    def test_it_is_zero_inside_and_restored_after(self):
        seen = {}

        class Helper:
            @without_implicit_wait
            def check(self, driver):
                seen["inside"] = driver.timeouts.implicit_wait
                return "result"

        driver = FakeDriver()
        assert Helper().check(driver) == "result"
        assert seen["inside"] == 0
        assert driver.timeouts.implicit_wait == 5

    def test_it_is_restored_when_the_check_raises(self):
        class Helper:
            @without_implicit_wait
            def check(self, driver):
                raise RuntimeError("boom")

        driver = FakeDriver()
        with pytest.raises(RuntimeError):
            Helper().check(driver)
        assert driver.timeouts.implicit_wait == 5

    @pytest.mark.parametrize(
        "name",
        [
            "_detect_captcha_or_challenge",
            "_detect_subscription_wall",
            "_try_close_modals",
            "_page_has_article_content",
        ],
    )
    def test_every_presence_check_runs_without_it(self, name):
        assert hasattr(getattr(ContentExtractor, name), "__wrapped__")


class TestTheKeywordIsWeighedAgainstTheStory:
    def _extractor(self, has_story: bool):
        extractor = ContentExtractor.__new__(ContentExtractor)
        extractor._phase = MagicMock()
        extractor._page_has_article_content = lambda driver: has_story
        return extractor

    def test_a_script_beside_a_story_is_not_blocking(self):
        driver = FakeDriver("<script src='https://www.google.com/recaptcha/api.js'>")
        assert self._extractor(True)._detect_captcha_or_challenge(driver) is False

    def test_a_keyword_with_no_story_still_blocks(self):
        driver = FakeDriver("<div>recaptcha</div>")
        assert self._extractor(False)._detect_captcha_or_challenge(driver) is True
