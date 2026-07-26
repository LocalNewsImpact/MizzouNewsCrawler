"""A paywall wall is filed as paywalled, not retried and not stored as a body.

Observed in production 2026-07-26: greenfieldvedette.com served 1,039 chars
consisting of its nav menu, the headline, the byline, and "This content is for
subscribers only." That cleared the 400-char stub threshold, so the old
length-only gate accepted it and it would have been written to the corpus as an
article whose body is furniture. The capture-quality gate rejected it, but then
escalated to Selenium -- which spent ~3 minutes and recovered nothing, because
the same wall is served to a real browser.

So: recognise the wall, skip the browser, keep the metadata the page did expose
(headline/byline/date live outside the wall), and drop the wall text.
"""

import pytest

from src.crawler import ContentExtractor
from src.utils.boilerplate import (
    PAYWALL_MARKERS,
    SUBSCRIPTION_MARKERS,
    looks_like_paywall,
)

# The real capture, trimmed. Keeping it verbatim matters: it is the evidence
# that a wall can be long enough to pass a length check.
GREENFIELD_WALL = (
    "Home Categories Business Columns Featured Letter to Editor Local News "
    "News Obituaries Photo Galleries Schools Sports Calendar Special Pages "
    "GREENFIELD VEDETTE LAKE STOCKTON SHOPPER SUBSCRIBE SUBSCRIBE LOGIN LOGIN "
    "Login with Facebook Martin Crowned Miller Football Homecoming Queen "
    "by Krista Guy "
    "This content is for subscribers only. Log in or sign up for a free trial "
    "below. Click here to start your Free Trial (No credit card required)"
)

REAL_ARTICLE = (
    "The city council voted Tuesday to approve the new budget after a lengthy "
    "public hearing that drew more than fifty residents to the chamber. "
    "Council members said the plan preserves funding for the library and the "
    "fire department while trimming administrative costs. The measure passed "
    "on a five to two vote and takes effect in July. Opponents argued the "
    "increase in fees would fall hardest on renters, and asked the council "
    "to revisit the proposal in the fall when revenue figures are final. "
    "The city manager said the budget reflects three months of review by "
    "department heads and a citizens advisory panel that met weekly. "
)


@pytest.fixture
def extractor():
    ex = ContentExtractor.__new__(ContentExtractor)
    ex.PAYWALL_STUB_MAX_CHARS = ContentExtractor.PAYWALL_STUB_MAX_CHARS
    return ex


class TestPaywallDetection:
    def test_detects_the_real_greenfield_wall(self):
        assert looks_like_paywall(GREENFIELD_WALL) == (
            "this content is for subscribers only"
        )

    def test_real_article_is_not_a_paywall(self):
        assert looks_like_paywall(REAL_ARTICLE) is None

    def test_prose_mentioning_subscribers_is_not_a_paywall(self):
        """Phrase-level matching: bare words appear inside real reporting."""
        assert (
            looks_like_paywall(
                "Subscribers to the streaming service said prices rose again, "
                "and the company confirmed it will not offer refunds."
            )
            is None
        )

    def test_newsletter_ask_is_not_a_wall(self):
        """A newsletter prompt is furniture beside a story, not a wall
        replacing one -- it must not trigger the paywall path."""
        assert looks_like_paywall("Subscribe to our newsletter for updates.") is None

    def test_empty_and_none_are_safe(self):
        assert looks_like_paywall(None) is None
        assert looks_like_paywall("") is None

    def test_markers_are_shared_not_duplicated(self):
        """The cleaner and the gate must read one list, not two that drift.

        Every wall phrase the cleaner strips should also be recognised as a
        wall here; PAYWALL_MARKERS additionally carries prompts observed in
        production that the stripping list lacks.
        """
        shared = {
            "this item is available in full to subscribers",
            "please log in to continue reading",
        }
        assert shared <= set(SUBSCRIPTION_MARKERS)
        assert shared <= set(PAYWALL_MARKERS)
        # Newsletter asks belong to the cleaner's list only.
        assert "subscribe to our newsletter" in SUBSCRIPTION_MARKERS
        assert "subscribe to our newsletter" not in PAYWALL_MARKERS


class TestPaywallSkipsSelenium:
    def test_wall_does_not_escalate(self, extractor):
        """The core saving: a browser gets the same wall, so do not spend one."""
        result = {"content": GREENFIELD_WALL, "url": "https://gv.com/story"}

        assert extractor._selenium_would_add_value(result, ["publish_date"]) is False
        assert extractor._last_capture_rejection == "paywall"
        assert extractor._last_paywall_marker == (
            "this content is for subscribers only"
        )

    def test_wall_is_flagged_for_the_save_path(self, extractor):
        result = {"content": GREENFIELD_WALL, "url": "https://gv.com/story"}

        extractor._selenium_would_add_value(result, ["publish_date"])

        meta = result["metadata"]
        assert meta["capture_rejected_as"] == "paywall"
        assert meta["paywall_marker"] == "this content is for subscribers only"
        assert meta["capture_quality"]["is_paywall"] is True

    def test_non_paywall_junk_still_escalates(self, extractor):
        """Only walls skip the browser. Other non-article captures (a nav dump,
        a JS shell) may still be recoverable by rendering, so they escalate."""
        nav_dump = (
            "Home News Sports Obituaries Classifieds Weather Opinion Business "
            "Living Calendar Contact Us Advertise Newsletters Archives Jobs "
        ) * 6
        result = {"content": nav_dump, "url": "https://example.com/story"}

        assert extractor._selenium_would_add_value(result, ["author"]) is True
        assert extractor._last_capture_rejection == "not_article_like"

    def test_real_article_unaffected(self, extractor):
        result = {"content": REAL_ARTICLE, "url": "https://example.com/story"}

        assert extractor._selenium_would_add_value(result, ["author"]) is False
        assert extractor._last_capture_rejection is None
        assert result["metadata"]["capture_quality"]["is_paywall"] is False

    def test_quality_signals_recorded_for_walls_too(self, extractor):
        """Walls are judged by the same measured signals as everything else,
        so the marker list can be audited rather than trusted."""
        result = {"content": GREENFIELD_WALL, "url": "https://gv.com/story"}

        extractor._selenium_would_add_value(result, ["publish_date"])

        q = result["metadata"]["capture_quality"]
        assert q["article_like"] is False
        assert "prose_density" in q
        assert "capitalization_ratio" in q
        assert "utility_word_rate" in q
