"""Re-asking the matching question over 2.97M stored entity rows.

The rules changed: exact only, normalised before comparison, scoped to
the states a source actually reaches. Every existing match was made under
the old ones -- `fuzz.ratio >= 0.85` against one publisher's 22-mile
slice -- so they have to be asked again, and the ones that no longer hold
have to be CLEARED. Leaving them keeps exactly what this replaces: "St.
Louis City" filed under St. Louis County, 206 times.

spaCy is not re-run. `entity_text` is stored, and what changed is the
matching, not the extraction.
"""

from __future__ import annotations

from src.pipeline.entity_extraction import Feature, rematch_source
from src.utils.gazetteer_names import normalize_name


def _feature(name, category="schools"):
    return Feature(
        id=f"f-{name.lower().replace(' ', '-')}",
        name=name,
        name_norm=normalize_name(name),
        category=category,
    )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """Answers the paging query from a queue, records the updates."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.updates = []
        self.commits = 0

    def execute(self, statement, params=None):
        if isinstance(params, list):
            self.updates.extend(params)
            return _Result([])
        return _Result(self.pages.pop(0) if self.pages else [])

    def commit(self):
        self.commits += 1


class TestWhatItRewrites:
    def test_a_name_that_still_matches_keeps_a_match(self):
        session = _Session([[("e1", "Mizzou Arena", "mizzou arena", "old-id")], []])
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert counts["matched"] == 1
        assert session.updates[0]["matched_gazetteer_id"] == "f-mizzou-arena"
        assert session.updates[0]["match_score"] == 1.0

    def test_a_stale_match_is_cleared(self):
        """THE POINT. "St. Louis City" matched St. Louis COUNTY at 0.857
        under the old threshold. It must not survive the rematch."""
        session = _Session([[("e1", "St. Louis City", "st louis city", "old-id")], []])
        counts = rematch_source(
            session, "s1", [_feature("St. Louis County", "government")]
        )
        assert counts["cleared"] == 1
        assert session.updates[0]["matched_gazetteer_id"] is None
        assert session.updates[0]["match_score"] is None
        assert session.updates[0]["match_name"] is None

    def test_the_normalisation_is_rewritten(self):
        """The gate reads `entity_norm`, so a possessive that never
        matched before has to be stored in the new form."""
        session = _Session([[("e1", "Kansas City's", "kansas city's", None)], []])
        rematch_source(session, "s1", [_feature("Kansas City", "government")])
        assert session.updates[0]["entity_norm"] == "kansas city"
        assert session.updates[0]["match_name"] == "Kansas City"

    def test_the_gazetteer_category_is_recorded(self):
        session = _Session([[("e1", "Westminster College", "x", None)], []])
        rematch_source(session, "s1", [_feature("Westminster College", "schools")])
        assert session.updates[0]["osm_category"] == "schools"

    def test_an_unmatched_row_that_is_already_correct_is_left_alone(self):
        """2.97M rows: writing every one of them for nothing is the
        difference between a job that finishes and one that does not."""
        session = _Session([[("e1", "Trump", "trump", None)], []])
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert counts["unchanged"] == 1
        assert session.updates == []


class TestPaging:
    def test_it_pages_until_the_source_is_exhausted(self):
        session = _Session(
            [
                [("e1", "Mizzou Arena", "x", None)],
                [("e2", "Mizzou Arena", "x", None)],
                [],
            ]
        )
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert counts["read"] == 2

    def test_no_rows_is_not_an_error(self):
        counts = rematch_source(_Session([[]]), "s1", [_feature("Mizzou Arena")])
        assert counts == {"read": 0, "matched": 0, "cleared": 0, "unchanged": 0}


class TestSafety:
    def test_the_dry_run_writes_nothing(self):
        session = _Session([[("e1", "Mizzou Arena", "x", None)], []])
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")], dry_run=True)
        assert counts["matched"] == 1
        assert session.updates == []
        assert session.commits == 0

    def test_no_features_clears_rather_than_keeping_old_matches(self):
        """A source scoped to a state with no gazetteer must not keep
        matches made against a different one."""
        session = _Session([[("e1", "Mizzou Arena", "x", "old-id")], []])
        counts = rematch_source(session, "s1", [])
        assert counts["cleared"] == 1
