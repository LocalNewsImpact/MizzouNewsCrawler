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
        self.deleted = []
        self.parked = []
        self.commits = 0

    def execute(self, statement, params=None):
        if isinstance(params, list):
            self.updates.extend(params)
            return _Result([])
        if isinstance(params, dict) and "ids" in params:
            if "DELETE" in str(statement):
                self.deleted.extend(params["ids"])
            else:
                self.parked.extend(params["ids"])
            return _Result([])
        return _Result(self.pages.pop(0) if self.pages else [])

    def commit(self):
        self.commits += 1


class TestWhatItRewrites:
    def test_a_name_that_still_matches_keeps_a_match(self):
        session = _Session(
            [
                [
                    (
                        "e1",
                        "Mizzou Arena",
                        "mizzou arena",
                        "old-id",
                        "a1",
                        "ORG",
                        "spacy",
                    )
                ],
                [],
            ]
        )
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert counts["matched"] == 1
        assert session.updates[0]["matched_feature_id"] == "f-mizzou-arena"
        assert session.updates[0]["match_score"] == 1.0

    def test_a_stale_match_is_cleared(self):
        """THE POINT. "St. Louis City" matched St. Louis COUNTY at 0.857
        under the old threshold. It must not survive the rematch."""
        session = _Session(
            [
                [
                    (
                        "e1",
                        "St. Louis City",
                        "st louis city",
                        "old-id",
                        "a1",
                        "ORG",
                        "spacy",
                    )
                ],
                [],
            ]
        )
        counts = rematch_source(
            session, "s1", [_feature("St. Louis County", "government")]
        )
        assert counts["cleared"] == 1
        assert session.updates[0]["matched_feature_id"] is None
        assert session.updates[0]["match_score"] is None
        assert session.updates[0]["match_name"] is None

    def test_the_normalisation_is_rewritten(self):
        """The gate reads `entity_norm`, so a possessive that never
        matched before has to be stored in the new form."""
        session = _Session(
            [[("e1", "Kansas City's", "kansas city's", None, "a1", "ORG", "spacy")], []]
        )
        rematch_source(session, "s1", [_feature("Kansas City", "government")])
        assert session.updates[0]["entity_norm"] == "kansas city"
        assert session.updates[0]["match_name"] == "Kansas City"

    def test_the_gazetteer_category_is_recorded(self):
        session = _Session(
            [[("e1", "Westminster College", "x", None, "a1", "ORG", "spacy")], []]
        )
        rematch_source(session, "s1", [_feature("Westminster College", "schools")])
        assert session.updates[0]["osm_category"] == "schools"

    def test_an_unmatched_row_that_is_already_correct_is_left_alone(self):
        """2.97M rows: writing every one of them for nothing is the
        difference between a job that finishes and one that does not."""
        session = _Session([[("e1", "Trump", "trump", None, "a1", "ORG", "spacy")], []])
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert counts["unchanged"] == 1
        assert session.updates == []


class TestPaging:
    def test_it_pages_until_the_source_is_exhausted(self):
        session = _Session(
            [
                [("e1", "Mizzou Arena", "x", None, "a1", "ORG", "spacy")],
                [("e2", "Mizzou Arena", "x", None, "a1", "ORG", "spacy")],
                [],
            ]
        )
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert counts["read"] == 2

    def test_no_rows_is_not_an_error(self):
        counts = rematch_source(_Session([[]]), "s1", [_feature("Mizzou Arena")])
        assert counts == {
            "read": 0,
            "matched": 0,
            "cleared": 0,
            "unchanged": 0,
            "deduped": 0,
        }


class TestSafety:
    def test_the_dry_run_writes_nothing(self):
        session = _Session(
            [[("e1", "Mizzou Arena", "x", None, "a1", "ORG", "spacy")], []]
        )
        counts = rematch_source(session, "s1", [_feature("Mizzou Arena")], dry_run=True)
        assert counts["matched"] == 1
        assert session.updates == []
        assert session.commits == 0

    def test_no_features_clears_rather_than_keeping_old_matches(self):
        """A source scoped to a state with no gazetteer must not keep
        matches made against a different one."""
        session = _Session(
            [[("e1", "Mizzou Arena", "x", "old-id", "a1", "ORG", "spacy")], []]
        )
        counts = rematch_source(session, "s1", [])
        assert counts["cleared"] == 1


class TestRowsThatCollapseOntoEachOther:
    """`article_entities` is unique on (article_id, entity_norm,
    entity_label, extractor_version). Rewriting the norm collapses rows
    that used to differ -- "Tesla" and "Tesla's" both become "tesla" --
    so two rows land on one key and the UPDATE fails on the constraint.
    It did, over 2.9M rows:

        Key (article_id, entity_norm, entity_label, extractor_version)=
        (6b0c3a1a..., tesla, ORG, spacy-en_core_web_sm-3.8.7)
        already exists.

    They are the same entity under the new rule, so the surplus row goes
    rather than being kept with a stale norm.
    """

    def _rows(self):
        return [
            ("e1", "Tesla", "tesla", None, "a1", "ORG", "spacy"),
            ("e2", "Tesla's", "tesla's", None, "a1", "ORG", "spacy"),
        ]

    def test_the_second_row_is_deleted_not_updated(self):
        session = _Session([self._rows(), []])
        counts = rematch_source(session, "s1", [_feature("Tesla", "economic")])
        assert counts["deduped"] == 1
        assert counts["matched"] == 1

    def test_deletes_run_before_updates(self):
        """An update landing on a key a surplus row still holds fails on
        the constraint, so the order is not incidental."""
        session = _Session([self._rows(), []])
        rematch_source(session, "s1", [_feature("Tesla", "economic")])
        assert session.deleted == ["e2"]

    def test_a_different_label_is_not_a_collision(self):
        """The key includes the label: the same name as an ORG and as a
        GPE are two rows and always were."""
        session = _Session(
            [
                [
                    ("e1", "Tesla", "tesla", None, "a1", "ORG", "spacy"),
                    ("e2", "Tesla", "tesla", None, "a1", "GPE", "spacy"),
                ],
                [],
            ]
        )
        counts = rematch_source(session, "s1", [_feature("Tesla", "economic")])
        assert counts["deduped"] == 0

    def test_a_different_article_is_not_a_collision(self):
        session = _Session(
            [
                [
                    ("e1", "Tesla", "tesla", None, "a1", "ORG", "spacy"),
                    ("e2", "Tesla", "tesla", None, "a2", "ORG", "spacy"),
                ],
                [],
            ]
        )
        assert (
            rematch_source(session, "s1", [_feature("Tesla", "economic")])["deduped"]
            == 0
        )

    def test_a_collision_across_a_page_boundary_is_still_caught(self):
        """One article's entities can straddle a batch."""
        session = _Session(
            [
                [("e1", "Tesla", "tesla", None, "a1", "ORG", "spacy")],
                [("e2", "Tesla's", "tesla's", None, "a1", "ORG", "spacy")],
                [],
            ]
        )
        assert (
            rematch_source(session, "s1", [_feature("Tesla", "economic")])["deduped"]
            == 1
        )


class TestTheWriteCannotCollideWithItself:
    """The unique key is (article_id, entity_norm, entity_label,
    extractor_version), and a new norm is frequently a norm ANOTHER row
    still holds -- "the Missouri Department of Transportation" and
    "Missouri Department of Transportation" both resolve to the latter.
    When that other row is on a later page it has not been rewritten
    yet, so the update collides with a value about to disappear. It did,
    against production:

        Key (article_id, entity_norm, entity_label, extractor_version)=
        (73d48e55..., missouri department of transportation, ORG, ...)
        already exists.

    Parking each row on its own id first makes the intermediate state
    unique by construction.
    """

    def test_rows_are_parked_before_their_real_values_are_written(self):
        session = _Session(
            [[("e1", "Mizzou Arena", "old", None, "a1", "ORG", "spacy")], []]
        )
        rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert session.parked == ["e1"]
        assert session.updates[0]["entity_norm"] == "mizzou arena"

    def test_nothing_is_parked_when_nothing_changes(self):
        session = _Session([[("e1", "Trump", "trump", None, "a1", "ORG", "spacy")], []])
        rematch_source(session, "s1", [_feature("Mizzou Arena")])
        assert session.parked == []

    def test_the_dry_run_parks_nothing(self):
        session = _Session(
            [[("e1", "Mizzou Arena", "old", None, "a1", "ORG", "spacy")], []]
        )
        rematch_source(session, "s1", [_feature("Mizzou Arena")], dry_run=True)
        assert session.parked == []
