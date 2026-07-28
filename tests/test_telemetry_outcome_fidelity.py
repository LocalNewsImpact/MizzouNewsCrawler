"""Telemetry must report what the pipeline actually did.

Three defects found by reading 6h of production rows on 2026-07-27, all of the
same shape -- telemetry re-deriving or inventing a fact it was never told:

1. ``finalize()`` decided success by re-running ``looks_like_article()`` on the
   body. But the furniture/paywall gate EMPTIES the body before finalize, so a
   deliberate filter was indistinguishable from a failed capture: 407 rows
   landed as is_success=false with no error_type and no message. They are why
   the failure rate read as 27% when much of it was by-design filtering.

2. The same re-derivation disagreed in the other direction: 75 rows stored as
   ``status='extracted'`` WITH a body were recorded as failures, because
   ``looks_like_article()`` is stricter than the save path. The pipeline kept
   the article; telemetry called it a loss.

3. ``_determine_primary_extraction_method()`` returned a hardcoded
   "newspaper4k" when nothing was tracked, inventing an attribution for
   whatever really ran and inflating newspaper4k in per-method analysis.

Plus the dead feedback loop: every AMP event the crawler emitted was missing
from SENSITIVITY_ADJUSTMENT_RULES, so all of them hit "Unknown event type, no
adjustment".
"""

import pytest

from src.utils.bot_sensitivity_manager import (
    SENSITIVITY_ADJUSTMENT_RULES,
    SENSITIVITY_FLOOR,
)
from src.utils.comprehensive_telemetry import ExtractionMetrics

ARTICLE = "The council approved the measure on Tuesday evening. " * 8


def _metrics():
    return ExtractionMetrics("op", "art", "https://example.com/s", "example.com")


class TestFilteredOutcomesAreDistinguishable:
    """A deliberate filter must not look like a failed extraction."""

    @pytest.mark.parametrize("outcome", ["paywall", "not_article"])
    def test_filter_records_a_reason(self, outcome):
        m = _metrics()
        # The gate empties the body before finalize -- that is the whole problem.
        m.finalize({"title": "Headline", "content": ""}, outcome=outcome)

        assert m.is_success is False
        assert m.error_type == f"filtered_{outcome}", "must not be a bare failure"
        assert m.error_message, "a filtered row must say why"

    def test_filtered_is_not_confusable_with_a_real_error(self):
        """The 551 silent rows had error_type IS NULL -- that is the tell."""
        m = _metrics()
        m.finalize({"content": ""}, outcome="not_article")
        assert m.error_type is not None


class TestPipelineVerdictWins:
    """The caller knows the outcome; telemetry must not overrule it."""

    def test_stored_article_is_not_recorded_as_a_failure(self):
        """The 75-row contradiction: saved as extracted, logged as failed."""
        m = _metrics()
        # Short body the save path accepted but looks_like_article() rejects.
        m.finalize({"title": "Headline", "content": "Brief item."}, outcome="extracted")
        assert m.is_success is True

    def test_wire_counts_as_a_success(self):
        m = _metrics()
        m.finalize({"title": "H", "content": ARTICLE}, outcome="wire")
        assert m.is_success is True
        assert m.error_type is None

    def test_without_an_outcome_the_body_still_decides(self):
        """Callers that pass no verdict keep the old inference."""
        good = _metrics()
        good.finalize({"title": "H", "content": ARTICLE})
        assert good.is_success is True

        empty = _metrics()
        empty.finalize({"title": "H", "content": ""})
        assert empty.is_success is False

    def test_content_length_still_reflects_the_stored_body(self):
        m = _metrics()
        m.finalize({"content": ARTICLE}, outcome="extracted")
        assert m.content_length == len(ARTICLE)


class TestAttributionIsNotInvented:
    """An untracked method is "unknown", not a guess dressed up as a fact."""

    def test_no_tracked_methods_reports_unknown(self):
        from src.crawler import ContentExtractor

        ex = ContentExtractor.__new__(ContentExtractor)
        # Used to return "newspaper4k" here, inflating it in every per-method
        # analysis for whatever method had actually run.
        assert ex._determine_primary_extraction_method({"extraction_methods": {}}) == (
            "unknown"
        )

    def test_a_tracked_method_is_still_reported(self):
        from src.crawler import ContentExtractor

        ex = ContentExtractor.__new__(ContentExtractor)
        result = {"extraction_methods": {"content": "mcmetadata"}}
        assert ex._determine_primary_extraction_method(result) == "mcmetadata"

    def test_none_valued_methods_do_not_count_as_tracked(self):
        from src.crawler import ContentExtractor

        ex = ContentExtractor.__new__(ContentExtractor)
        result = {"extraction_methods": {"content": "none", "title": None}}
        assert ex._determine_primary_extraction_method(result) == "unknown"


class TestAmpEventsAdjustSensitivity:
    """Every event the crawler emits must have a rule, or the loop is dead."""

    @pytest.mark.parametrize(
        "event",
        [
            "amp_preemptive_success",
            "amp_bypass_success",
            "amp_bypass_failure",
            "captcha_detected",
        ],
    )
    def test_emitted_event_is_known(self, event):
        assert event in SENSITIVITY_ADJUSTMENT_RULES

    @pytest.mark.parametrize("event", ["amp_preemptive_success", "amp_bypass_success"])
    def test_success_relaxes_rather_than_tightens(self, event):
        increase, _, _ = SENSITIVITY_ADJUSTMENT_RULES[event]
        assert increase < 0, "a working fetch must not raise sensitivity"

    def test_bypass_failure_tightens(self):
        increase, _, _ = SENSITIVITY_ADJUSTMENT_RULES["amp_bypass_failure"]
        assert increase > 0

    def test_every_rule_stays_inside_the_valid_range(self):
        """A negative adjustment must not be able to undershoot the floor."""
        for event, (increase, max_cap, _) in SENSITIVITY_ADJUSTMENT_RULES.items():
            for current in range(SENSITIVITY_FLOOR, 11):
                new = max(SENSITIVITY_FLOOR, min(current + increase, max_cap))
                assert SENSITIVITY_FLOOR <= new <= 10, f"{event} at {current} -> {new}"
