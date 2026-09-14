"""`sources.county` was written straight from the spreadsheet.

Nothing looked at it, and two different faults came through that gap on
2026-09-14, both of them visible to a reviewer in the visual builder.

A KANSAS CITY TELEVISION STATION WAS FILED UNDER "Nexstar Media Inc" --
its owner, in the county column -- and the builder duly offered "Nexstar
County" as a place to pick newsrooms from.

AND ONE COUNTY WAS TWO. "Callaway" and "Callaway County" sat side by
side in the tree, each holding one newsroom, and so did "St. Louis" and
"St Louis" -- eighteen sources against three. That reads as two counties
with one paper apiece rather than one county with two.

Both stop at the load now. A value that resolves is written in the
gazetteer's spelling, so a county can only ever have one; a value that
does not resolve is not written, and the row is named in the summary.
"""

from __future__ import annotations

import pytest

from src.cli.commands.load_sources import resolve_county


class TestItWritesTheGazetteersSpelling:
    """One spelling per county, chosen by the gazetteer rather than by
    whoever typed the spreadsheet."""

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("Callaway", "Callaway"),
            ("Callaway County", "Callaway"),
            ("Jackson County", "Jackson"),
            ("St Louis", "St. Louis"),
            ("St. Louis", "St. Louis"),
        ],
    )
    def test_a_suffix_or_a_missing_period_resolves_to_one_name(self, given, expected):
        assert resolve_county("MO", given) == (expected, None)

    def test_the_two_spellings_that_split_a_county_now_agree(self):
        """THE BUG, stated as the thing that can no longer happen."""
        assert resolve_county("MO", "Callaway")[0] == (
            resolve_county("MO", "Callaway County")[0]
        )
        assert resolve_county("MO", "St Louis")[0] == (
            resolve_county("MO", "St. Louis")[0]
        )

    def test_an_internal_capital_survives(self):
        """`DeKalb` is a real county and title-casing would make it
        "Dekalb". The gazetteer's own spelling is what gets written, so
        nothing here has to guess at case."""
        assert resolve_county("MO", "DeKalb") == ("DeKalb", None)

    def test_a_county_in_another_state_resolves_against_that_state(self):
        assert resolve_county("WA", "Grays Harbor") == ("Grays Harbor", None)


class TestItRefusesWhatIsNotACounty:
    def test_an_owner_name_is_not_written(self):
        """`fox4kc.com` carried "Nexstar Media Inc". The row still loads;
        the county does not."""
        name, why = resolve_county("MO", "Nexstar Media Inc")
        assert name is None
        assert "not a county in MO" in why

    def test_a_county_from_the_wrong_state_is_refused(self):
        """There is a Kings in New York and California, and none in
        Washington. Checking against the row's own state is the point."""
        name, why = resolve_county("WA", "Kings")
        assert name is None

    def test_an_empty_county_says_so_rather_than_failing(self):
        assert resolve_county("MO", "") == (None, "no county given")
        assert resolve_county("MO", "   ") == (None, "no county given")


class TestTheMessageHelpsFixTheSpreadsheet:
    def test_a_typo_gets_suggestions(self):
        """A rejection that only says no leaves somebody grepping a
        census file."""
        _, why = resolve_county("MO", "Calaway")
        assert "Did you mean" in why
        assert "Callaway" in why

    def test_the_suggestions_name_their_state(self):
        """The closest match is often in another state -- "Calaway"
        offers Callaway in Missouri and Calloway in Kentucky -- and which
        is meant is the operator's call, not ours."""
        _, why = resolve_county("MO", "Calaway")
        assert "(MO)" in why
        assert "(KY)" in why

    def test_a_spelled_out_saint_is_suggested_back(self):
        _, why = resolve_county("MO", "Saint Louis")
        assert "St. Louis (MO)" in why

    def test_suggestions_are_looked_up_by_name_not_by_state(self):
        """THE ARGUMENT ORDER. `canonical_county(state, name)` and
        `suggest_counties(name, prefer_state)` take theirs the opposite
        way round, and calling the second like the first hunts for a
        county called "MO" and returns nothing -- so every message lost
        its suggestions and an empty list read exactly like no close
        match."""
        _, why = resolve_county("MO", "Bonne")
        assert "Did you mean" in why, why


class TestWhatItWillNotGuessAt:
    def test_without_a_state_the_name_is_kept_as_written(self):
        """There is a Lincoln county in two dozen states. A value that
        cannot be checked is not thereby wrong."""
        assert resolve_county("", "Boone") == ("Boone", None)
        assert resolve_county("   ", "Lincoln") == ("Lincoln", None)


class TestTheLoadUsesIt:
    def _source(self):
        from pathlib import Path

        return (
            Path(__file__).resolve().parent.parent / "src/cli/commands/load_sources.py"
        ).read_text()

    def test_the_row_is_resolved_before_it_is_written(self):
        source = self._source()
        assert "resolve_county(" in source
        assert 'county=row["county"]' not in source, "the raw column is written again"

    def test_an_existing_source_is_corrected_too(self):
        """A load is the moment the spreadsheet speaks. Leaving existing
        rows alone is why one bad county survived months of loads."""
        source = self._source()
        assert "existing_source.county = county" in source

    def test_the_problems_are_reported_together(self):
        """One warning per row scrolls past; a list at the end is a work
        item."""
        source = self._source()
        assert "county_problems" in source
        assert "loaded without a" in source
