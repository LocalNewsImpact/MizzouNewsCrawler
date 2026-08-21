"""The §11 unit table: profile resolution, status transitions, point
resolution, scope gating, reprocessing candidacy, response parsing, cost.

The adapter is stubbed wholesale; nothing here touches a model or a database.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from src.enrichment import orchestrator
from src.enrichment.gate import HEURISTIC_REJECT, boilerplate_score
from src.enrichment.profiles import (
    DEFAULT_PROFILE,
    ConfigurationError,
    Profile,
    configured_steps,
    missing_steps,
    parse_profile,
)
from src.enrichment.resolve import norm, resolve_point
from src.enrichment.types import ArticleInput, StepResult

MODEL = "test-model"
ARTICLE = ArticleInput(
    "a1", "Title", "Body text. " * 100, "Mizzou-Missouri-State", "Columbia"
)

FULL = Profile(
    version=2,
    content_gate=True,
    scope=True,
    places=True,
    people=True,
    organizations=True,
    metadata_presets=(
        "subject",
        "topic",
        "format",
        "temporal_orientation",
        "user_need",
    ),
)


def ok(step, payload, cost="0.001"):
    return StepResult(step, True, payload, None, 100, 10, Decimal(cost))


def fail(step):
    return StepResult(step, False, None, "TimeoutError: upstream", 0, 0, Decimal("0"))


def meta(category, confidence=0.9):
    return {"article_metadata": {"category": category, "confidence": confidence}}


class StubAdapter:
    """Programmable adapter; records which steps were called."""

    def __init__(self, **overrides):
        self.calls = []
        self.overrides = overrides

    def _result(self, step, default):
        self.calls.append(step)
        value = self.overrides.get(step, default)
        return value(step) if callable(value) else value

    def run_content_gate(self, article, model):
        return self._result(
            "content_gate", ok("content_gate", {"verdict": "news", "reason": ""})
        )

    def run_scope(self, article, model):
        return self._result("scope", ok("scope", meta("city_municipality")))

    def run_places(self, article, model):
        return self._result("places", ok("places", {"locations": []}))

    def run_people(self, article, model):
        return self._result("people", ok("people", {"people": []}))

    def run_organizations(self, article, model):
        return self._result("organizations", ok("organizations", {"organizations": []}))

    def run_preset(self, article, preset, model):
        self.calls.append(preset)
        value = self.overrides.get(preset, ok(preset, meta("x")))
        return value(preset) if callable(value) else value


def run(profile, article=ARTICLE, attempts=0, **overrides):
    stub = StubAdapter(**overrides)
    with patch.object(orchestrator, "adapter", stub):
        result = orchestrator.enrich_article(
            article, profile, model=MODEL, attempts=attempts, max_attempts=3
        )
    return result, stub


# ---- profile resolution -----------------------------------------------------


class TestProfiles:
    def test_missing_profile_is_the_default(self):
        assert parse_profile(None) == DEFAULT_PROFILE
        assert DEFAULT_PROFILE.content_gate and not DEFAULT_PROFILE.scope

    def test_all_some_none_step_lists(self):
        assert configured_steps(FULL) == [
            "content_gate",
            "scope",
            "places",
            "subject",
            "topic",
            "format",
            "temporal_orientation",
            "user_need",
            "people",
            "organizations",
        ]
        some = parse_profile(
            {"version": 1, "scope": True, "metadata_presets": ["topic"]}
        )
        assert configured_steps(some) == ["content_gate", "scope", "topic"]
        none = parse_profile({"version": 1, "content_gate": False})
        assert configured_steps(none) == []

    @pytest.mark.parametrize(
        "raw,fragment",
        [
            ({"version": 1, "bogus": True}, "unknown profile keys"),
            ({"version": "one"}, "must be an integer"),
            ({}, "must be an integer"),
            ({"version": 1, "metadata_presets": ["information_needs"]}, "excluded"),
            ({"version": 1, "metadata_presets": ["geographic_scope"]}, "'scope' flag"),
            (
                {"version": 1, "metadata_presets": ["subjects"]},
                "unknown metadata presets",
            ),
            ({"version": 1, "metadata_presets": ["topic", "topic"]}, "duplicates"),
            (
                {"version": 1, "scope": True, "places": True, "geocode": True},
                "not implemented",
            ),
            ({"version": 1, "geocode": True}, "requires places"),
            ({"version": 1, "places": True}, "requires scope"),
            ({"version": 1, "scope": "yes"}, "must be a boolean"),
        ],
    )
    def test_invalid_profiles_are_rejected(self, raw, fragment):
        with pytest.raises(ConfigurationError, match=fragment):
            parse_profile(raw)


# ---- status transitions -----------------------------------------------------


class TestStatusTransitions:
    def test_full_profile_yields_enriched(self):
        result, stub = run(FULL)
        assert result.status == "enriched"
        assert result.skip_reason is None
        assert result.steps_applied == configured_steps(FULL)

    def test_empty_profile_yields_skipped_profile_none(self):
        result, stub = run(Profile(version=1, content_gate=False))
        assert result.status == "enrichment_skipped"
        assert result.skip_reason == "profile_none"
        assert stub.calls == []

    def test_gate_not_news_is_terminal_not_article(self):
        result, _ = run(
            FULL,
            content_gate=ok(
                "content_gate", {"verdict": "not_news", "reason": "cookie boilerplate"}
            ),
        )
        assert result.status == "not_article"

    def test_gate_paywall_is_terminal_paywall(self):
        result, _ = run(
            FULL,
            content_gate=ok(
                "content_gate", {"verdict": "paywall", "reason": "teaser only"}
            ),
        )
        assert result.status == "paywall"

    def test_heuristic_reject_skips_the_gate_call(self):
        junk = ArticleInput(
            "a2", "T", "cookies consent privacy policy " * 10, "ds", None
        )
        assert boilerplate_score(junk.content) >= HEURISTIC_REJECT
        result, stub = run(FULL, article=junk)
        assert result.status == "not_article"
        assert stub.calls == []  # free rejection: no model call at all

    def test_transient_failure_stays_labeled(self):
        result, _ = run(FULL, scope=fail("scope"))
        assert result.status == "labeled"
        assert result.skip_reason is None

    def test_attempts_exhausted_yields_failed_max_attempts(self):
        result, _ = run(FULL, attempts=2, scope=fail("scope"))
        assert result.status == "enrichment_skipped"
        assert result.skip_reason == "failed_max_attempts"

    def test_failure_discards_partial_steps(self):
        result, _ = run(FULL, people=fail("people"))
        assert result.status == "labeled"
        # steps_applied reflects what ran, but the caller must not persist a
        # labeled outcome as enrichment: nothing is written for retries.

    def test_mid_run_failure_aborts_remaining_steps(self):
        _, stub = run(FULL, subject=fail("subject"))
        assert "topic" not in stub.calls  # aborted at the failure


# ---- scope gating -----------------------------------------------------------


class TestScopeGating:
    def test_regional_reaches_places_for_per_place_geoids(self):
        _, stub = run(FULL, scope=ok("scope", meta("regional")))
        assert "places" in stub.calls

    @pytest.mark.parametrize(
        "scope_value",
        [
            "statewide",
            "national",
            "international",
            "other",
            "elsewhere_to_local",
            "local_to_elsewhere",
        ],
    )
    def test_non_places_scopes_never_reach_places(self, scope_value):
        result, stub = run(FULL, scope=ok("scope", meta(scope_value)))
        assert result.status == "enriched"
        assert "places" not in stub.calls
        assert "places" not in result.steps_applied

    @pytest.mark.parametrize(
        "scope_value", ["city_municipality", "neighborhood_community"]
    )
    def test_point_scopes_reach_places(self, scope_value):
        result, stub = run(FULL, scope=ok("scope", meta(scope_value)))
        assert "places" in stub.calls
        assert "places" in result.steps_applied


# ---- point resolution -------------------------------------------------------


def loc(city):
    return {"location": {"components": {"city": city}}}


class TestPointResolution:
    def test_single_city_wins(self):
        assert resolve_point({"locations": [loc("Columbia")]}, "Jefferson City") == (
            "Columbia",
            "single_city",
        )

    def test_publication_city_breaks_ties(self):
        payload = {"locations": [loc("Columbia"), loc("Ashland")]}
        assert resolve_point(payload, "Ashland") == ("Ashland", "publication_city")

    def test_multiple_cities_without_publication_match_is_unresolved(self):
        payload = {"locations": [loc("Columbia"), loc("Ashland")]}
        assert resolve_point(payload, "Sedalia") is None

    def test_zero_cities_is_unresolved(self):
        assert resolve_point({"locations": []}, "Columbia") is None

    def test_normalization(self):
        assert norm("  Lee's   Summit, MO.") == "lee's summit mo"
        assert norm("The Dalles") == "dalles"
        payload = {"locations": [loc("LEE'S SUMMIT"), loc("Lee's Summit")]}
        assert resolve_point(payload, None) == ("LEE'S SUMMIT", "single_city")


# ---- response parsing -------------------------------------------------------


class TestResponseParsing:
    @pytest.mark.parametrize(
        "payload",
        [
            {},  # no article_metadata
            {"article_metadata": {"confidence": 0.9}},  # category missing
            {"article_metadata": {"category": ""}},  # category empty
            {"article_metadata": {"category": "x", "confidence": 1.7}},  # out of range
            {
                "article_metadata": {"category": "x", "confidence": "high"}
            },  # not numeric
        ],
    )
    def test_bad_classification_fails_the_article(self, payload):
        result, _ = run(FULL, subject=ok("subject", payload))
        assert result.status == "labeled"  # fails, retries; no bad row written


# ---- reprocessing candidacy (the pure half) --------------------------------


class TestReprocessingDelta:
    def test_only_missing_steps_are_paid_for(self):
        applied = ["content_gate", "scope", "subject"]
        assert missing_steps(FULL, applied) == [
            "places",
            "topic",
            "format",
            "temporal_orientation",
            "user_need",
            "people",
            "organizations",
        ]

    def test_nothing_missing_when_all_applied(self):
        assert missing_steps(FULL, configured_steps(FULL)) == []

    def test_bypassed_article_pays_for_everything(self):
        assert missing_steps(FULL, []) == configured_steps(FULL)


# ---- cost accounting --------------------------------------------------------


class TestCost:
    def test_total_is_the_sum_of_step_costs(self):
        result, _ = run(FULL)
        assert result.total_cost_usd == sum(
            (r.cost_usd for r in result.results), Decimal("0")
        )
        assert result.total_cost_usd > 0


# ---- dataset-specific export exclusion by scope -----------------------------

EXCLUDING = Profile(
    version=3,
    content_gate=True,
    scope=True,
    places=True,
    people=True,
    organizations=True,
    metadata_presets=("subject", "topic"),
    export_exclude_scopes=("international", "national"),
)


class TestScopeExportExclusion:
    def test_excluded_scope_is_terminal_out_of_scope(self):
        result, stub = run(EXCLUDING, scope=ok("scope", meta("international")))
        assert result.status == "out_of_scope"
        assert result.skip_reason is None
        assert result.steps_applied == ["content_gate", "scope"]

    def test_exclusion_skips_every_remaining_step(self):
        _, stub = run(EXCLUDING, scope=ok("scope", meta("national")))
        for step in ("places", "subject", "topic", "people", "organizations"):
            assert step not in stub.calls, f"{step} ran on an excluded article"

    def test_non_excluded_broad_scope_still_enriches(self):
        result, _ = run(EXCLUDING, scope=ok("scope", meta("statewide")))
        assert result.status == "enriched"  # statewide not in this dataset's list

    def test_point_scope_unaffected_by_the_flag(self):
        result, stub = run(EXCLUDING, scope=ok("scope", meta("city_municipality")))
        assert result.status == "enriched"
        assert "places" in stub.calls

    def test_default_profile_excludes_nothing(self):
        result, _ = run(FULL, scope=ok("scope", meta("international")))
        assert result.status == "enriched"

    @pytest.mark.parametrize(
        "raw,fragment",
        [
            (
                {
                    "version": 1,
                    "scope": True,
                    "export_exclude_scopes": ["city_municipality"],
                },
                "not excludable",
            ),
            (
                {"version": 1, "scope": True, "export_exclude_scopes": ["galactic"]},
                "not excludable",
            ),
            (
                {"version": 1, "export_exclude_scopes": ["international"]},
                "requires scope",
            ),
            (
                {
                    "version": 1,
                    "scope": True,
                    "export_exclude_scopes": ["national", "national"],
                },
                "duplicates",
            ),
            (
                {"version": 1, "scope": True, "export_exclude_scopes": "national"},
                "list of strings",
            ),
        ],
    )
    def test_invalid_exclusion_flags_are_rejected(self, raw, fragment):
        with pytest.raises(ConfigurationError, match=fragment):
            parse_profile(raw)

    def test_since_floor_parses_and_validates(self):
        profile = parse_profile({"version": 2, "steady_state_since": "2026-08-21"})
        assert profile.steady_state_since == "2026-08-21"
        with pytest.raises(ConfigurationError, match="ISO date"):
            parse_profile({"version": 2, "steady_state_since": "August 21"})

    def test_parse_accepts_the_flag(self):
        profile = parse_profile(
            {
                "version": 2,
                "scope": True,
                "export_exclude_scopes": ["international", "national"],
            }
        )
        assert profile.export_exclude_scopes == ("international", "national")
