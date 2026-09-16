"""Why a central place survived the gate, recorded where it is known.

`grounded` accepts a place for one of two reasons: the article names it,
or the article names an institution that sits there. Both are
defensible; they are not equally strong. The second is induction --
sound, wanted, and the reason the statewide gazetteer exists -- and 167
of the corpus's central places rest on it alone.

The reason is computed against the article text during enrichment and
was then thrown away. datadesk does the reviewing and cannot recompute
it: it has no access to the gate and no reason to. So it is stored.
"""

from __future__ import annotations

import pytest

from src.enrichment.grounding import INSTITUTION, NAMED, support_for

STORY = "Tolton athletics look to start spring seasons strong."


class TestWhichReasonKeptIt:
    def test_a_place_the_article_names(self):
        assert support_for("Columbia", content="The council met in Columbia.") == NAMED

    def test_a_place_only_an_institution_supports(self):
        assert (
            support_for("Columbia", content=STORY, institution_places=["Columbia"])
            == INSTITUTION
        )

    def test_naming_wins_over_induction(self):
        """A place the article says is NAMED, whatever else is there.
        Reporting to reason from beats reasoning from an institution."""
        assert (
            support_for(
                "Columbia",
                content="The council met in Columbia.",
                institution_places=["Columbia"],
            )
            == NAMED
        )

    def test_neither_is_None_not_a_reason(self):
        assert support_for("Columbia", content=STORY) is None
        assert (
            support_for("Columbia", content=STORY, institution_places=["Fulton"])
            is None
        )

    def test_it_agrees_with_grounded(self):
        """`grounded` is this read as a boolean; a disagreement would mean
        the gate and the queue described different corpora."""
        from src.enrichment.grounding import grounded

        cases = [
            ("Columbia", "The council met in Columbia.", None),
            ("Columbia", STORY, ["Columbia"]),
            ("Columbia", STORY, None),
            ("Columbia", STORY, ["Fulton"]),
        ]
        for name, body, places in cases:
            reason = support_for(name, content=body, institution_places=places)
            truth = grounded(name, content=body, institution_places=places)
            assert (reason is not None) is truth


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, points=(), cities=()):
        self._points = list(points)
        self._cities = list(cities)
        self.statements = []
        self.params = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        if len(self.statements) == 1:
            return _Result(self._points)
        if len(self.statements) == 2:
            return _Result(self._cities)
        return _Result()

    def commit(self):
        self.commits += 1


NAMED_ROW = [("a1", "Columbia", "The council met in Columbia.", "T", "Mexico")]
INDUCED_ROW = [("a1", "Columbia", STORY, "T", "Mexico")]


class TestTheBackfill:
    def test_it_counts_each_reason(self):
        from src.enrichment.repository import backfill_point_support

        counts = backfill_point_support(_Session(NAMED_ROW), dry_run=True)
        assert counts["named"] == 1 and counts["institution"] == 0

    def test_institution_evidence_is_used(self):
        from src.enrichment.repository import backfill_point_support

        session = _Session(INDUCED_ROW, [("a1", "Columbia")])
        counts = backfill_point_support(session, dry_run=True)
        assert counts["institution"] == 1

    def test_the_dry_run_writes_nothing(self):
        from src.enrichment.repository import backfill_point_support

        session = _Session(NAMED_ROW)
        backfill_point_support(session, dry_run=True)
        assert session.commits == 0
        assert not [s for s in session.statements if "UPDATE" in s]

    def test_it_writes_and_commits(self):
        from src.enrichment.repository import backfill_point_support

        session = _Session(NAMED_ROW)
        backfill_point_support(session, dry_run=False)
        assert session.commits >= 1
        assert session.params[-1] == {"id": "a1", "support": "named"}

    def test_state_level_points_are_not_read(self):
        """`name_for('29')` is "MO", which no story prints, so a state
        rung is exempt from grounding and has no support to record."""
        from src.enrichment.repository import backfill_point_support

        session = _Session()
        backfill_point_support(session, dry_run=True)
        assert "point_geoid_level IN ('place', 'county')" in session.statements[0]

    def test_nothing_to_do_is_not_an_error(self):
        from src.enrichment.repository import backfill_point_support

        assert backfill_point_support(_Session(), dry_run=True)["read"] == 0


class TestTheWritePathRecordsItToo:
    """A backfill that is not matched on the write path decays: every
    article enriched after it has a null reason."""

    @pytest.fixture
    def source(self):
        from pathlib import Path

        return Path("src/enrichment/repository.py").read_text()

    def test_the_column_is_inserted(self, source):
        assert "point_support," in source
        assert ":point_support," in source

    def test_it_is_updated_on_conflict(self, source):
        assert "point_support = EXCLUDED.point_support" in source

    def test_it_is_computed_from_the_same_evidence_as_the_gate(self, source):
        assert "institution_places=named_places," in source
