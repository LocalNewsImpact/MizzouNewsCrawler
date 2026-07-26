"""A capture that is not article text must not be accepted as one.

The gap this pins: _selenium_would_add_value() gated on LENGTH only, so a
consent wall, a bot-challenge interstitial or a nav dump that cleared the
paywall-stub threshold was accepted as a successful extraction. The
project already knows how to tell writing from furniture --
boilerplate.looks_like_article(), used by comprehensive_telemetry to set
is_success -- but that verdict only ever got RECORDED, never acted on.
Now it drives escalation, and the reason is recorded so the failure mode
is visible instead of silent.
"""

import pytest

from src.crawler import ContentExtractor


@pytest.fixture
def extractor():
    ex = ContentExtractor.__new__(ContentExtractor)
    ex.PAYWALL_STUB_MAX_CHARS = ContentExtractor.PAYWALL_STUB_MAX_CHARS
    return ex


# Real prose: survives the strip, so it reads as writing.
ARTICLE_BODY = (
    "The city council voted Tuesday to approve the new budget after a "
    "lengthy public hearing that drew more than fifty residents to the "
    "chamber. Council members said the plan preserves funding for the "
    "library and the fire department while trimming administrative costs. "
    "The measure passed on a five to two vote and takes effect in July. "
    "Opponents argued the increase in fees would fall hardest on renters, "
    "and asked the council to revisit the proposal in the fall. "
)


class TestCaptureQualityGate:
    def test_real_article_is_accepted_without_escalation(self, extractor):
        result = {"content": ARTICLE_BODY, "url": "https://example.com/story"}

        assert extractor._selenium_would_add_value(result, ["author"]) is False
        assert extractor._last_capture_rejection is None

    def test_empty_capture_escalates(self, extractor):
        result = {"content": "", "url": "https://example.com/story"}

        assert extractor._selenium_would_add_value(result, ["content"]) is True
        assert extractor._last_capture_rejection == "empty"

    def test_paywall_stub_escalates(self, extractor):
        result = {"content": "Short teaser.", "url": "https://example.com/story"}

        assert extractor._selenium_would_add_value(result, ["content"]) is True
        assert extractor._last_capture_rejection == "stub"

    def test_nav_dump_long_enough_to_pass_length_still_escalates(self, extractor):
        """THE gap: a menu/nav capture is long, but it is not writing."""
        nav_dump = (
            "Home News Sports Obituaries Classifieds Subscribe Log In "
            "Weather Opinion Business Living Calendar Contact Us Advertise "
            "Newsletters Archives Legal Notices Public Records Jobs Autos "
            "Real Estate Marketplace Events Photos Videos Podcasts Store "
        ) * 3
        assert len(nav_dump) > extractor.PAYWALL_STUB_MAX_CHARS
        result = {"content": nav_dump, "url": "https://example.com/story"}

        assert extractor._selenium_would_add_value(result, ["author"]) is True
        assert extractor._last_capture_rejection == "not_article_like"

    def test_rejection_reason_resets_between_captures(self, extractor):
        """A stale reason must not leak onto the next, good capture."""
        bad = {"content": "", "url": "https://example.com/a"}
        extractor._selenium_would_add_value(bad, ["content"])
        assert extractor._last_capture_rejection == "empty"

        good = {"content": ARTICLE_BODY, "url": "https://example.com/b"}
        extractor._selenium_would_add_value(good, ["author"])
        assert extractor._last_capture_rejection is None


class TestQualityTelemetryIsEvaluable:
    """Signals must be recorded for ACCEPTED captures too.

    A sample of rejections alone cannot yield a false-positive rate or
    justify a threshold change -- the accepted population is exactly what
    you need to compare against.
    """

    def test_accepted_capture_still_records_signals(self, extractor):
        result = {"content": ARTICLE_BODY, "url": "https://example.com/story"}

        extractor._selenium_would_add_value(result, ["author"])

        quality = result["metadata"]["capture_quality"]
        assert quality["article_like"] is True
        assert quality["chars"] == len(ARTICLE_BODY.strip())
        assert quality["prose_density"] > 0
        # The thresholds that produced the verdict travel with it, so rows
        # stay interpretable after a retune.
        assert quality["thresholds"]["min_prose_density"] > 0

    def test_rejected_capture_records_the_same_signals(self, extractor):
        nav_dump = (
            "Home News Sports Obituaries Classifieds Subscribe Log In "
            "Weather Opinion Business Living Calendar Contact Us Advertise "
        ) * 8
        result = {"content": nav_dump, "url": "https://example.com/story"}

        extractor._selenium_would_add_value(result, ["author"])

        quality = result["metadata"]["capture_quality"]
        assert quality["article_like"] is False
        assert "prose_density" in quality
        assert "capitalization_ratio" in quality
        assert "utility_word_rate" in quality

    def test_empty_capture_records_signals_without_crashing(self, extractor):
        result = {"content": "", "url": "https://example.com/story"}

        extractor._selenium_would_add_value(result, ["content"])

        quality = result["metadata"]["capture_quality"]
        assert quality["chars"] == 0
        assert quality["article_like"] is False

    def test_assessment_never_breaks_extraction(self, extractor, monkeypatch):
        """Measurement is diagnostic: it must not be able to fail a capture."""
        monkeypatch.setattr(
            "src.crawler.strip_boilerplate",
            lambda body: (_ for _ in ()).throw(ValueError("boom")),
        )

        quality = extractor._assess_capture_quality(ARTICLE_BODY)

        assert "error" in quality
        assert quality["chars"] > 0
