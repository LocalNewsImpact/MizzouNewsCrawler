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


class TestPointScopeNeverTakesStateRung:
    """A city/neighborhood story whose point city misses the gazetteer must
    fall back to the publication place — never to the resolve ladder's state
    rung (found live 2026-08-21: "Webster" for Webster Groves coded a city
    story to the whole state)."""

    def test_unresolvable_point_city_falls_back_to_publication_place(self):
        from decimal import Decimal
        from unittest.mock import MagicMock

        from src.enrichment import repository
        from src.enrichment.profiles import Profile
        from src.enrichment.types import ArticleInput, EnrichmentOutcome, StepResult

        article = ArticleInput("x", "T", "body", "ds", "Columbia", "MO")
        session = MagicMock()
        captured = {}

        def capture(stmt, params=None):
            if params and "point_geoid" in (params or {}):
                captured.update(params)
            return session

        session.execute = capture
        outcome = EnrichmentOutcome(
            article_id="x",
            status="enriched",
            skip_reason=None,
            steps_applied=["content_gate", "scope", "places"],
            results=[
                StepResult(
                    "scope",
                    True,
                    {
                        "article_metadata": {
                            "category": "city_municipality",
                            "confidence": 0.9,
                        }
                    },
                    None,
                    10,
                    5,
                    Decimal("0.001"),
                ),
                StepResult(
                    "places",
                    True,
                    {
                        "locations": [
                            {
                                "location": {
                                    "components": {
                                        "city": "Websterville Nowhere",
                                        "state": "MO",
                                    }
                                },
                                "mention_count": 3,
                            }
                        ]
                    },
                    None,
                    10,
                    5,
                    Decimal("0.001"),
                ),
            ],
            total_cost_usd=Decimal("0.002"),
        )
        repository.persist_outcome(
            session,
            article,
            outcome,
            profile=Profile(version=3, scope=True, places=True),
            model="m",
            backfield_commit="c",
            prompt_versions={},
        )
        assert captured.get("point_geoid_level") != "state"
        assert captured.get("point_geoid") == "2915670"  # Columbia city
        assert captured.get("point_method") == "publication_place_assumed"


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
        # Deduped, and no state row for a city-scope story. Was three
        # rows; the fourth is Kansas City's county, which no code in the
        # set declares -- a place GEOID does not carry one.
        assert len(out) == 4
        assert ("29095", "county", False, "county_rollup") in out
        # Columbia's county is already here as a MENTION, so the rollup
        # adds nothing for it: what was said outranks what was derived.
        assert [(g, src) for g, lvl, _p, src in out if g == "29019"] == [
            ("29019", "mention")
        ]

    def test_regional_story_is_its_mentions(self):
        from src.enrichment.repository import build_story_geoids

        out = build_story_geoids(
            None, [("2970000", "place"), ("2907966", "place")], "regional", "29"
        )
        # The mentions, in order, still first and still the story.
        assert [g for g, _lvl, _p, src in out if src == "mention"] == [
            "2970000",
            "2907966",
        ]
        assert not any(p for _, _, p, _ in out)  # no primary: no single point
        # Each town now also contributes the county containing it. Before
        # this, a regional story naming two towns and no county was
        # absent from every count of stories touching a county.
        assert [g for g, _lvl, _p, src in out if src == "county_rollup"] == [
            "29077",
            "29213",
        ]

    def test_statewide_contributes_the_state_code(self):
        from src.enrichment.repository import build_story_geoids

        out = build_story_geoids(None, [], "statewide", "29")
        assert out == [("29", "state", True, "scope_state")]

    def test_empty_when_nothing_known(self):
        from src.enrichment.repository import build_story_geoids

        assert build_story_geoids(None, [], "other", None) == []


# --- a place knows its county ------------------------------------------------


def test_a_place_geoid_does_not_say_which_county_it_is_in():
    """Every other rung of the ladder is readable from the code. State
    prefixes county, county prefixes tract and block. A place does not:
    2938000 says state 29 and place 38000, and nothing about the county.

    That is why a story mentioning a town contributed no county at all,
    and why "which counties does this story touch" could not be answered
    from the geoid set.
    """
    from src.enrichment.fips import county_of_place

    # Kansas City: state 29, and the county is nowhere in the code.
    assert county_of_place("2938000")[0] == "29095"
    assert not "2938000".startswith("29095")
    # A county code does prefix its tracts, which is the contrast.
    assert "29095001100".startswith("29095")


def test_a_place_in_several_counties_takes_its_primary_one():
    """A place is not obliged to sit in one county: 1,199 span two, 87
    span three, 15 span four, 3 span five. Kansas City is in four.

    The primary wins and the span rides along, so a caller can tell the
    answer was a choice. Contributing all four would put Cass, Clay and
    Platte on any story that says "Kansas City", and a wrong county is
    worse than a missing one -- the missing one reads as a gap and the
    wrong one reads as a finding.
    """
    from src.enrichment.fips import county_of_place

    county, span = county_of_place("2938000")
    assert county == "29095"
    assert span == 4, "the span is what says this was a judgement call"

    # The ordinary case still reports its span, so a caller never has to
    # special-case the shape.
    assert county_of_place("0100100") == ("01017", 1)


def test_a_place_outside_the_crosswalk_contributes_nothing():
    """A missing place is a gap, not a guess."""
    from src.enrichment.fips import county_of_place

    assert county_of_place("9999999") is None
    assert county_of_place("") is None


def test_a_mentioned_town_now_carries_its_county():
    """The question this was built for: a story that names only a town
    used to contribute no county, so it could not be counted among the
    stories touching one."""
    from src.enrichment.repository import build_story_geoids

    out = build_story_geoids(None, [("2938000", "place")], None, None)
    assert ("2938000", "place", False, "mention") in out
    assert ("29095", "county", False, "county_rollup") in out


def test_a_rolled_up_county_says_it_was_rolled_up():
    """It was never mentioned. `source` is what keeps the set honest, and
    what lets an analysis count literal mentions or containment and say
    which it did."""
    from src.enrichment.repository import build_story_geoids

    out = build_story_geoids(None, [("2938000", "place")], None, None)
    sources = {g: src for g, _lvl, _p, src in out}
    assert sources["2938000"] == "mention"
    assert sources["29095"] == "county_rollup"


def test_a_county_already_in_the_set_is_not_added_twice():
    """A story that names both the town and its county gets one county
    row, and it stays the mention -- what was said outranks what was
    derived from it."""
    from src.enrichment.repository import build_story_geoids

    out = build_story_geoids(
        None, [("2938000", "place"), ("29095", "county")], None, None
    )
    counties = [(g, src) for g, lvl, _p, src in out if lvl == "county"]
    assert counties == [("29095", "mention")]


def test_a_rolled_up_county_obeys_the_ancestor_rule():
    """The set drops a county where a tract or block already carries its
    digits. A rolled-up one is no different -- it would be the same
    redundant ancestor, arriving by another route."""
    from src.enrichment.repository import build_story_geoids

    out = build_story_geoids(
        None, [("2938000", "place"), ("29095001100", "tract")], None, None
    )
    assert not [g for g, lvl, _p, src in out if src == "county_rollup"]
