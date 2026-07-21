"""Tell a blocking wall from a widget that merely sits on the page.

A bot wall replaces the article; a sign-in or subscription prompt does not. The
detector used to treat any reCAPTCHA iframe as a wall, so pages that embed one
in a subscriber sign-in widget paid ~86s per article failing to "bypass" a login
form — then extracted the article anyway (telemetry showed selenium 11/11
"success" alongside "Could not bypass").

The rule is structural, not a vendor list: does the page still carry prose?
Content is now judged from the HTML *snapshot* (``page_source`` parsed in-process)
rather than reading each ``<p>.text`` live — the live read cost up to 124s on
heavy pages (one WebDriver round-trip per element, each forcing a layout reflow)
while the browser itself stayed responsive. Hard challenges (Cloudflare,
PerimeterX) must still block regardless of lingering prose.
"""

import pytest

from src.crawler import ContentExtractor


def _page(paragraphs):
    """Wrap paragraph strings in a minimal article document."""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f"<html><body><article>{body}</article></body></html>"


# 8 substantial paragraphs — clears both the >=5 paragraph and >=1200 char bars.
_SENTENCE = (
    "A paragraph of real article text that runs on for a while and keeps going. "
)
PROSE_HTML = _page([_SENTENCE * 4 for _ in range(8)])
# 6 paragraphs (clears the count bar) but far under the char bar — an
# interstitial, not a story; exercises the char threshold specifically.
THIN_HTML = _page(["Enable JavaScript and cookies to continue."] * 6)
# No paragraphs at all.
EMPTY_HTML = "<html><body><div>Loading…</div></body></html>"


class FakeElement:
    pass


class FakeDriver:
    """Serves the content snapshot via ``page_source`` and answers challenge
    selectors via ``find_elements`` (which is all ``_detect_captcha_or_challenge``
    still uses live)."""

    def __init__(self, page_source, challenge_selectors=()):
        self.page_source = page_source
        self._challenge = set(challenge_selectors)
        self.title = "A story headline"
        self.current_url = "https://example.com/news/story"

    def find_elements(self, by, selector):
        return [FakeElement()] if selector in self._challenge else []


@pytest.fixture
def extractor():
    return ContentExtractor.__new__(ContentExtractor)


def test_article_prose_is_recognised(extractor):
    assert extractor._page_has_article_content(FakeDriver(PROSE_HTML)) is True


def test_interstitial_is_not_mistaken_for_an_article(extractor):
    assert extractor._page_has_article_content(FakeDriver(THIN_HTML)) is False


def test_no_paragraphs_at_all(extractor):
    assert extractor._page_has_article_content(FakeDriver(EMPTY_HTML)) is False


def test_probe_failure_does_not_assert_content(extractor):
    """If the probe cannot read the page, it must not claim the page is fine."""

    class Broken:
        @property
        def page_source(self):
            raise RuntimeError("driver gone")

    assert extractor._page_has_article_content(Broken()) is False


def test_signin_widget_on_a_real_article_does_not_block(extractor):
    """The case that cost ~86s per article."""
    driver = FakeDriver(PROSE_HTML, {"iframe[src*='recaptcha']"})

    assert extractor._detect_captcha_or_challenge(driver) is False


def test_recaptcha_on_a_contentless_page_still_blocks(extractor):
    """Same widget, no article — that is a wall and must be treated as one."""
    driver = FakeDriver(THIN_HTML, {"iframe[src*='recaptcha']"})

    assert extractor._detect_captcha_or_challenge(driver) is True


def test_cloudflare_challenge_blocks_even_with_prose(extractor):
    """Hard challenges are not exempted by lingering markup."""
    driver = FakeDriver(PROSE_HTML, {".cf-challenge-form"})

    assert extractor._detect_captcha_or_challenge(driver) is True


def test_perimeterx_blocks_even_with_prose(extractor):
    driver = FakeDriver(PROSE_HTML, {"#px-captcha"})

    assert extractor._detect_captcha_or_challenge(driver) is True
