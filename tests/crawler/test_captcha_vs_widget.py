"""Tell a blocking wall from a widget that merely sits on the page.

A bot wall replaces the article; a sign-in or subscription prompt does not. The
detector used to treat any reCAPTCHA iframe as a wall, so pages that embed one
in a subscriber sign-in widget paid ~86s per article failing to "bypass" a login
form — then extracted the article anyway (telemetry showed selenium 11/11
"success" alongside "Could not bypass").

The rule is structural, not a vendor list: does the rendered page still carry
prose? Hard challenges (Cloudflare, PerimeterX) must still block regardless.
"""

import pytest

from src.crawler import ContentExtractor


class FakeElement:
    def __init__(self, text=""):
        self.text = text


class FakeDriver:
    """Answers CSS queries from a {selector_substring: [elements]} map."""

    def __init__(self, matches, page_source="<html><body>page</body></html>"):
        self._matches = matches
        self.page_source = page_source
        self.title = "A story headline"
        self.current_url = "https://example.com/news/story"

    def find_elements(self, by, selector):
        # Exact match only. Substring matching bites here: the paragraph key
        # "p" is a substring of "iframe[src*='recaptcha']", which would make
        # every selector return prose.
        if "p" in self._matches and selector == "article p, main p, p":
            return self._matches["p"]
        return self._matches.get(selector, [])


PROSE = [FakeElement("A paragraph of real article text that runs on. " * 4)] * 8
THIN = [FakeElement("Enable JavaScript and cookies to continue")]


@pytest.fixture
def extractor():
    return ContentExtractor.__new__(ContentExtractor)


def test_article_prose_is_recognised(extractor):
    assert extractor._page_has_article_content(FakeDriver({"p": PROSE})) is True


def test_interstitial_is_not_mistaken_for_an_article(extractor):
    assert extractor._page_has_article_content(FakeDriver({"p": THIN})) is False


def test_no_paragraphs_at_all(extractor):
    assert extractor._page_has_article_content(FakeDriver({})) is False


def test_probe_failure_does_not_assert_content(extractor):
    """If the probe cannot tell, it must not claim the page is fine."""

    class Broken:
        def find_elements(self, *_a):
            raise RuntimeError("driver gone")

    assert extractor._page_has_article_content(Broken()) is False


def test_signin_widget_on_a_real_article_does_not_block(extractor):
    """The case that cost ~86s per article."""
    driver = FakeDriver({"p": PROSE, "iframe[src*='recaptcha']": [FakeElement()]})

    assert extractor._detect_captcha_or_challenge(driver) is False


def test_recaptcha_on_a_contentless_page_still_blocks(extractor):
    """Same widget, no article — that is a wall and must be treated as one."""
    driver = FakeDriver({"p": THIN, "iframe[src*='recaptcha']": [FakeElement()]})

    assert extractor._detect_captcha_or_challenge(driver) is True


def test_cloudflare_challenge_blocks_even_with_prose(extractor):
    """Hard challenges are not exempted by lingering markup."""
    driver = FakeDriver({"p": PROSE, ".cf-challenge-form": [FakeElement()]})

    assert extractor._detect_captcha_or_challenge(driver) is True


def test_perimeterx_blocks_even_with_prose(extractor):
    driver = FakeDriver({"p": PROSE, "#px-captcha": [FakeElement()]})

    assert extractor._detect_captcha_or_challenge(driver) is True
