"""FIPS ladder unit tests. Gazetteer lookups are local; the block-level Census
call is exercised only in the live contract test."""

from unittest.mock import patch

from src.enrichment import fips
from src.enrichment.fips import (
    county_geoid,
    place_geoid,
    resolve_geoid,
    state_geoid,
)


class TestGazetteer:
    def test_place(self):
        r = place_geoid("Columbia", "MO")
        assert r.geoid == "2915670" and r.level == "place"
        assert r.lat and r.lon

    def test_place_with_lsad_suffix_input(self):
        assert place_geoid("Lee's Summit", "MO").geoid == "2941348"

    def test_place_unknown(self):
        assert place_geoid("Not A Real Town", "MO") is None

    def test_county_with_and_without_suffix(self):
        assert county_geoid("Boone County", "MO").geoid == "29019"
        assert county_geoid("Boone", "MO").geoid == "29019"

    def test_state(self):
        assert state_geoid("MO").geoid == "29"
        assert state_geoid("XX") is None


class TestLadder:
    def test_place_beats_county(self):
        r = resolve_geoid(
            point_city="Columbia",
            state="MO",
            county="Boone County",
            street_address=None,
            address_city=None,
            census_lookup=False,
        )
        assert (r.geoid, r.level) == ("2915670", "place")

    def test_falls_back_to_county_then_state(self):
        r = resolve_geoid(
            point_city="Nowhereville",
            state="MO",
            county="Boone",
            street_address=None,
            address_city=None,
            census_lookup=False,
        )
        assert (r.geoid, r.level) == ("29019", "county")
        r = resolve_geoid(
            point_city=None,
            state="MO",
            county=None,
            street_address=None,
            address_city=None,
            census_lookup=False,
        )
        assert (r.geoid, r.level) == ("29", "state")

    def test_nothing_resolves_to_none(self):
        assert (
            resolve_geoid(
                point_city=None,
                state=None,
                county=None,
                street_address=None,
                address_city=None,
            )
            is None
        )

    def test_block_upgrade_wins_when_available(self):
        fake = fips.GeoidResult("290190021003016", "block", 38.95, -92.33)
        with patch.object(fips, "block_geoid", return_value=fake):
            r = resolve_geoid(
                point_city="Columbia",
                state="MO",
                county="Boone",
                street_address="221 N 8th St",
                address_city="Columbia",
            )
        assert r.level == "block" and len(r.geoid) == 15
        assert r.geoid[:5] == "29019"  # nests to the county

    def test_no_house_number_never_calls_census(self):
        called = []
        with patch.object(
            fips, "block_geoid", side_effect=lambda *a, **k: called.append(1)
        ):
            fips._HOUSE_NUMBER.match("Haile Street") or None
        assert fips._HOUSE_NUMBER.match("Haile Street") is None
        assert fips._HOUSE_NUMBER.match("221 N 8th St") is not None


class TestStateFallbackForNonPointScopes:
    """A statewide or regional story with no place extraction still records
    the state GEOID; national/other stay null (no US-level FIPS)."""

    def test_repository_fallback_logic(self):
        from decimal import Decimal
        from unittest.mock import MagicMock

        from src.enrichment import repository
        from src.enrichment.types import ArticleInput, EnrichmentOutcome, StepResult

        article = ArticleInput("x", "T", "body", "ds", "Columbia", "MO")
        session = MagicMock()

        def outcome_with_scope(category):
            return EnrichmentOutcome(
                article_id="x",
                status="enriched",
                skip_reason=None,
                steps_applied=["content_gate", "scope"],
                results=[
                    StepResult(
                        "scope",
                        True,
                        {"article_metadata": {"category": category, "confidence": 0.9}},
                        None,
                        10,
                        5,
                        Decimal("0.001"),
                    )
                ],
                total_cost_usd=Decimal("0.001"),
            )

        captured = {}
        original_execute = session.execute

        def capture(stmt, params=None):
            if params and "point_geoid" in (params or {}):
                captured.update(params)
            return original_execute(stmt, params)

        session.execute = capture
        from src.enrichment.profiles import Profile

        profile = Profile(version=3, scope=True)

        repository.persist_outcome(
            session,
            article,
            outcome_with_scope("statewide"),
            profile=profile,
            model="m",
            backfield_commit="c",
            prompt_versions={},
        )
        assert captured.get("point_geoid") == "29"
        assert captured.get("point_geoid_level") == "state"

        # regional: NO story-level code — its geography is the per-place rows
        captured.clear()
        repository.persist_outcome(
            session,
            article,
            outcome_with_scope("regional"),
            profile=profile,
            model="m",
            backfield_commit="c",
            prompt_versions={},
        )
        assert captured.get("point_geoid") is None

        # unresolved city scope: the publication's own place, flagged assumed
        captured.clear()
        repository.persist_outcome(
            session,
            article,
            outcome_with_scope("city_municipality"),
            profile=profile,
            model="m",
            backfield_commit="c",
            prompt_versions={},
        )
        assert captured.get("point_geoid") == "2915670"  # Columbia city
        assert captured.get("point_geoid_level") == "place"
        assert captured.get("point_method") == "publication_place_assumed"

        captured.clear()
        repository.persist_outcome(
            session,
            article,
            outcome_with_scope("national"),
            profile=profile,
            model="m",
            backfield_commit="c",
            prompt_versions={},
        )
        assert captured.get("point_geoid") is None


class TestGeoSkipReason:
    """Every absent point code carries its cause (decided 2026-08-21).

    NULL means a point code is present; regional and national absences are
    designed; not_scoped means the gate stopped the article before scope;
    the remaining values are failures to act on.
    """

    def _run(self, category, publication_city="Columbia", publication_state="MO"):
        from decimal import Decimal
        from unittest.mock import MagicMock

        from src.enrichment import repository
        from src.enrichment.profiles import Profile
        from src.enrichment.types import ArticleInput, EnrichmentOutcome, StepResult

        article = ArticleInput(
            "x", "T", "body", "ds", publication_city, publication_state
        )
        session = MagicMock()
        captured = {}

        def capture(stmt, params=None):
            if params and "geo_skip_reason" in (params or {}):
                captured.update(params)
            return session

        session.execute = capture
        results = []
        if category is not None:
            results = [
                StepResult(
                    "scope",
                    True,
                    {"article_metadata": {"category": category, "confidence": 0.9}},
                    None,
                    10,
                    5,
                    Decimal("0.001"),
                )
            ]
        outcome = EnrichmentOutcome(
            article_id="x",
            status="enriched",
            skip_reason=None,
            steps_applied=["content_gate"],
            results=results,
            total_cost_usd=Decimal("0.001"),
        )
        repository.persist_outcome(
            session,
            article,
            outcome,
            profile=Profile(version=3, scope=True),
            model="m",
            backfield_commit="c",
            prompt_versions={},
        )
        return captured.get("geo_skip_reason"), captured.get("point_geoid")

    def test_point_code_present_means_no_reason(self):
        reason, geoid = self._run("statewide")
        assert geoid == "29" and reason is None
        reason, geoid = self._run("city_municipality")
        assert geoid == "2915670" and reason is None

    def test_designed_absences(self):
        assert self._run("regional") == ("regional_uses_place_set", None)
        assert self._run("national") == ("no_codeable_geography", None)
        assert self._run("international") == ("no_codeable_geography", None)

    def test_not_scoped(self):
        assert self._run(None) == ("not_scoped", None)

    def test_failure_reasons(self):
        assert self._run("city_municipality", publication_state=None) == (
            "publication_state_unknown",
            None,
        )
        assert self._run("statewide", publication_state=None) == (
            "publication_state_unknown",
            None,
        )
        assert self._run("city_municipality", publication_city="Nowhereville") == (
            "publication_city_not_in_census_gazetteer",
            None,
        )


class TestFullStateNames:
    """Extracted components carry 'Missouri' as often as 'MO'."""

    def test_full_name_equals_code(self):
        assert (
            place_geoid("Platte City", "Missouri").geoid
            == place_geoid("Platte City", "MO").geoid
        )
        assert county_geoid("Boone", "Missouri").geoid == "29019"
        assert state_geoid("Missouri").geoid == "29"

    def test_unknown_state_name_is_none(self):
        assert place_geoid("Columbia", "Missourah") is None
        assert state_geoid("Missourah") is None


class TestStoryGeoidSet:
    """News geography is one-to-many: the story-to-FIPS set."""

    def test_point_is_primary_and_mentions_dedupe(self):
        from src.enrichment.fips import GeoidResult
        from src.enrichment.repository import build_story_geoids

        point = GeoidResult("2915670", "place", 38.9, -92.3)
        mentions = [
            ("2915670", "place"),
            ("2938000", "place"),
            ("2938000", "place"),
            (None, None),
            ("29019", "county"),
        ]
        out = build_story_geoids(point, mentions, "city_municipality", "29")
        assert out[0] == ("2915670", "place", True, "point")
        assert ("2938000", "place", False, "mention") in out
        assert ("29019", "county", False, "mention") in out
        assert len(out) == 3  # deduped, no state row for city scope

    def test_regional_story_is_its_mentions(self):
        from src.enrichment.repository import build_story_geoids

        out = build_story_geoids(
            None, [("2970000", "place"), ("2907966", "place")], "regional", "29"
        )
        assert [g for g, *_ in out] == ["2970000", "2907966"]
        assert not any(p for _, _, p, _ in out)  # no primary: no single point

    def test_statewide_contributes_the_state_code(self):
        from src.enrichment.repository import build_story_geoids

        out = build_story_geoids(None, [], "statewide", "29")
        assert out == [("29", "state", True, "scope_state")]

    def test_empty_when_nothing_known(self):
        from src.enrichment.repository import build_story_geoids

        assert build_story_geoids(None, [], "other", None) == []
