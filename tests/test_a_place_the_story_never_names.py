"""Geography the article does not support is not recorded.

Measured against production on 2026-09-15: 17.2% of stored mentions and
9.7% of stored points named a place the article never names in
reporting. The counter-examples in this file are the real ones -- every
docstring below names an article that is in the corpus.

The FIPS ladder is deliberately not under test here: its city-to-county
agreement measured 100% and it is not where the error is. What it does
is carry one bad city up to a bad county, which is why
`TestTheLadderComesDownWithIt` exists.
"""

from __future__ import annotations

import pytest

from src.enrichment.grounding import dateline_city, fold, grounded, occurrences
from src.enrichment.reground import regrounded

KMIZ_IRAN = (
    "COLUMBIA, Mo. (KMIZ) -- B-2 bombers from Whiteman were used in the attack on Iran."
)
KOMU_WEATHER = (
    "A Madison man was killed Sunday afternoon after his buggy was hit by another "
    "vehicle Print Copy article link Save Currently in Columbia 45°F Sunny 45°F / "
    "36°F 9 AM 46°F 10 AM 50°F 11 AM 53°F"
)
RAIL = (
    "One woman was taken into custody following a Friday incident. Popular Stories "
    "Audrain County Missouri confirms first two cases of clade I mpox in state Two "
    "Wendy's locations in Columbia close over the weekend"
)


class TestAPlaceTheStoryNeverNames:
    """14.4% of mentions and 7.5% of points, the largest of the three
    failures by an order of magnitude."""

    def test_a_name_in_the_body_is_evidence(self):
        assert grounded("Columbia", content="The council met in Columbia on Tuesday.")

    def test_a_name_that_is_absent_is_not(self):
        """`aiming-high-mexico-high`, a Mexico, Missouri graduation story
        recorded as Boone County. It contains "Columbia" zero times."""
        assert not grounded(
            "Columbia",
            content="William Hernandez-Sampayo secured a spot at Harvard.",
        )

    def test_the_headline_counts_as_the_article(self):
        """`boil-water-advisory-issued-in-fulton` carries Fulton in its
        title. A place named only in the headline is still named."""
        assert grounded(
            "Fulton",
            content="The advisory takes effect Thursday.",
            title="Boil water advisory issued in Fulton",
        )

    def test_an_empty_name_is_not_grounded(self):
        assert not grounded("", content="Anything at all.")
        assert not grounded(None, content="Anything at all.")

    def test_an_empty_article_grounds_nothing(self):
        assert not grounded("Columbia", content=None)
        assert not grounded("Columbia", content="")


class TestThePublishersOwnDateline:
    """A dateline is the newsroom's address. It is evidence only when it
    names somewhere the newsroom is not."""

    def test_the_home_city_dateline_is_not_evidence(self):
        """`bombers-from-whiteman`: KMIZ is licensed to Columbia, so its
        dateline opens a story about B-2s over Iran."""
        assert not grounded("Columbia", content=KMIZ_IRAN, publication_city="Columbia")

    def test_a_dateline_elsewhere_is_evidence(self):
        """The rule is not "drop datelines". A Kirksville dateline on a
        Columbia station's story does locate that story in Kirksville."""
        assert grounded(
            "Kirksville",
            content="KIRKSVILLE, Mo. (KMIZ) -- A fire downtown.",
            publication_city="Columbia",
        )

    def test_the_same_dateline_from_another_newsroom_is_evidence(self):
        """Only the publisher's OWN city is disqualified."""
        assert grounded("Columbia", content=KMIZ_IRAN, publication_city="St. Joseph")

    def test_a_body_mention_survives_its_own_dateline(self):
        """A KMIZ story that is genuinely about Columbia still counts."""
        assert grounded(
            "Columbia",
            content="COLUMBIA, Mo. (KMIZ) -- The Columbia City Council met Monday.",
            publication_city="Columbia",
        )

    def test_the_byline_prefix_does_not_hide_the_dateline(self):
        """Some feeds put the byline first. Without matching it
        case-insensitively the dateline goes undetected and the rule
        silently stops applying."""
        assert dateline_city("By: Ryan Shiner COLUMBIA, Mo. (KMIZ) -- B-2 bombers") == (
            "COLUMBIA"
        )


class TestFurnitureIsNotReporting:
    """1.5% of mentions. `story_text` cannot reach any of this: March
    bodies were stored already flattened, so the widget and the reporting
    are a single segment and it strips nothing."""

    def test_a_weather_widget_is_not_a_mention(self):
        """`madison-man-killed-in-crash`: "Currently in Columbia 45°F"."""
        assert not grounded("Columbia", content=KOMU_WEATHER)

    def test_a_headline_rail_is_not_a_mention(self):
        assert not grounded("Columbia", content=RAIL)

    def test_a_reporters_biography_is_not_article_content(self):
        """The user's rule, 2026-09-15: a city in a sign-off line is not
        evidence the story went there."""
        assert not grounded(
            "Columbia",
            content="The board voted Tuesday. Jane Doe is a reporter who studied in Columbia.",
        )

    def test_furniture_elsewhere_does_not_condemn_a_real_mention(self):
        """One occurrence in reporting is enough, however much furniture
        the page also carries."""
        assert grounded(
            "Columbia",
            content="The Columbia City Council met Monday. " + KOMU_WEATHER,
        )


class TestNamesAreMatchedWholeAndInEveryForm:
    def test_a_short_name_does_not_match_inside_a_longer_word(self):
        """The defect that put 67,770 junk entity matches in the database
        in August: unbounded matching makes Unionville into Union."""
        assert not grounded("Union", content="The Unionville team won.")

    def test_the_abbreviated_and_spelled_saint_are_one_town(self):
        assert grounded("St. Louis", content="He drove to Saint Louis.")
        assert grounded("Saint Louis", content="He drove to St. Louis.")

    def test_the_apostrophe_is_optional(self):
        """Census files "Lee's Summit"; copy frequently drops it."""
        assert grounded("Lee's Summit", content="A fire in Lees Summit on Monday.")

    def test_folding_preserves_offsets(self):
        """The furniture window slices the lowercased text using offsets
        found in the folded one. If folding changed the length the window
        would drift and the rule would read the wrong sentence."""
        raw = "St. Louis — 45°F, Sunny; O'Fallon!"
        assert len(fold(raw)) == len(raw)

    def test_every_occurrence_is_found(self):
        folded = fold("Columbia today, Columbia tomorrow")
        assert len(occurrences("Columbia", folded)) == 2


class TestTheLadderComesDownWithIt:
    """The complaint that started this: "nothing about Boone here". The
    county was never mentioned -- it was rolled up from a city that was
    never mentioned either. County rollups are the largest category in
    `article_geoids` (17,819 rows against 16,796 mentions), so pruning
    the city and stopping leaves the whole complaint in place."""

    COLUMBIA, BOONE = "2915670", "29019"

    def _rows(self):
        return [
            (self.COLUMBIA, "place", True, "point"),
            (self.BOONE, "county", False, "county_rollup"),
        ]

    def test_an_ungrounded_city_takes_its_county_with_it(self):
        verdict = regrounded(
            self._rows(),
            content="A graduation in Mexico, Missouri.",
            publication_city="Mexico",
        )
        assert {row[0] for row in verdict.dropped} == {self.COLUMBIA, self.BOONE}
        assert verdict.kept == []

    def test_clearing_the_point_is_reported(self):
        """The dot has to come off the map too, not just the shading."""
        verdict = regrounded(
            self._rows(),
            content="A graduation in Mexico, Missouri.",
            publication_city="Mexico",
        )
        assert verdict.point_cleared

    def test_a_grounded_city_keeps_its_county(self):
        verdict = regrounded(
            self._rows(), content="The council met in Columbia on Tuesday."
        )
        assert verdict.dropped == []
        assert {row[0] for row in verdict.kept} == {self.COLUMBIA, self.BOONE}

    def test_the_county_is_recomputed_not_merely_kept(self):
        """A rollup nothing supports is dropped even when no city was."""
        verdict = regrounded(
            [
                ("2947704", "place", False, "mention"),
                ("29019", "county", False, "county_rollup"),
            ],
            content="A fire in Mexico on Monday.",
        )
        assert self.BOONE in {row[0] for row in verdict.dropped}

    def test_the_flat_column_excludes_the_point(self):
        """`article_enrichment.geoids` carries only non-primary codes
        (decided 2026-08-21); the point rides in its own columns."""
        verdict = regrounded(
            self._rows(), content="The council met in Columbia on Tuesday."
        )
        assert verdict.mention_codes == [self.BOONE]


class TestWhatTheBackfillMustNotTouch:
    def test_a_person_is_not_overruled_by_a_heuristic(self):
        rows = [("2915670", "place", False, "human")]
        verdict = regrounded(rows, content="Nothing about anywhere.")
        assert verdict.dropped == []

    def test_a_state_rung_is_not_read_as_a_name(self):
        """`name_for('29')` is "MO". Testing that as a place name drops
        all 2,070 state-level rows, because no story prints "MO" as a
        word. A state rung is reached by the ladder, not asserted."""
        rows = [("29", "state", True, "point")]
        verdict = regrounded(rows, content="A statewide story naming no city.")
        assert verdict.dropped == []

    def test_a_scope_state_row_is_a_classification_not_a_claim(self):
        rows = [("29", "state", False, "scope_state")]
        assert regrounded(rows, content="Anything.").dropped == []

    def test_an_unreadable_code_is_left_exactly_as_it_is(self):
        """Unverifiable is not unsupported. A backfill that cannot see
        something must not delete it."""
        rows = [("2999999", "place", False, "mention")]
        verdict = regrounded(rows, content="Nothing about anywhere.")
        assert verdict.dropped == []
        assert len(verdict.unverifiable) == 1


class TestTheWritePathUsesTheGate:
    """Asserted against the source: the gate is only worth having if the
    two places that mint geography both consult it."""

    @pytest.fixture
    def source(self):
        from pathlib import Path

        return Path("src/enrichment/repository.py").read_text()

    def test_the_point_claim_is_gated(self, source):
        assert 'if central.get("city") and _says(article, central["city"]):' in source

    def test_the_heuristic_point_is_gated(self, source):
        assert "if point and not _says(article, point[0]):" in source

    def test_the_mention_set_is_gated(self, source):
        assert "_says(article, name)" in source

    def test_there_is_one_reading_of_the_rule(self, source):
        """Two copies of "what counts as named" drift. `_says` is the
        single call site so the point and the mentions cannot disagree."""
        assert source.count("def _says(") == 1
        assert "grounded(" in source


class TestTheEdgesOfTheRules:
    """The guards that only fire on malformed or already-complete input.
    Each one exists because its absence is a crash or a duplicate rung,
    neither of which any earlier test reaches."""

    def test_a_name_with_no_letters_matches_nothing(self):
        """Folding "!!!" leaves nothing to search for. Building a pattern
        from an empty word list matches every position in the text."""
        assert not grounded("!!!", content="A story about !!! somewhere.")
        assert occurrences("!!!", fold("A story about !!! somewhere.")) == []

    def test_no_content_has_no_dateline(self):
        assert dateline_city(None) is None
        assert dateline_city("") is None

    def test_a_county_already_in_the_set_is_not_added_twice(self):
        """The city's county arrives as a rollup and the article also
        mentioned it. One rung per location."""
        rows = [
            ("2915670", "place", False, "mention"),
            ("29019", "county", False, "mention"),
        ]
        verdict = regrounded(
            rows, content="The Columbia council and Boone County commission met."
        )
        assert [row[0] for row in verdict.kept].count("29019") == 1

    def test_a_block_already_carries_its_countys_digits(self):
        """The ancestor rule the rest of the ladder obeys: a county is
        redundant where a block already states it."""
        rows = [
            ("2915670", "place", False, "mention"),
            ("290190001001000", "block", True, "point"),
        ]
        verdict = regrounded(rows, content="The Columbia council met at the site.")
        assert "29019" not in {row[0] for row in verdict.kept}
