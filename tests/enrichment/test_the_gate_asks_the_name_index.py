"""What the grounding gate accepts as institution evidence.

The gate keeps geography the model induced from an institution the story
names -- "a senior at Mexico High School" locates a story in Mexico. The
first version of that verifier asked the per-source gazetteer, filtered
by spaCy's entity label. Both were wrong.

THE LABEL IS A GUESS. Across 2.9M rows en_core_web_sm files `Columbia` as
ORG 3,047 times, `story` as ORG 2,999, `REWRITTEN` as ORG 1,726 and `Mo.`
as GPE 19,206. Filtering on that field is filtering on the unreliable one.

THE PER-SOURCE GAZETTEER IS CIRCULAR. Every row sits within 22.2 miles of
one publisher, so a match resolved near that publisher whatever the story
said -- and a chain business therefore resolved to the publisher's own
town, laundering the exact bias the gate exists to stop.

So the gate asks `gazetteer_name_places`: is this name, in a state this
source actually reaches, in exactly one Census place? walmart supercenter
occurs in 149 places, pizza hut in 140, aldi in 72, and none of them
locates anything.
"""

from __future__ import annotations

from src.enrichment.repository import institution_places


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []
        self.params = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _Result(self.rows)


class TestTheQuery:
    def _sql(self):
        session = _Session()
        institution_places(session, "a1")
        return session.statements[0]

    def test_it_requires_the_name_to_be_unambiguous(self):
        """The one rule that retires the chain problem, with no brand
        list to maintain."""
        assert "np.place_count = 1" in self._sql()

    def test_it_is_scoped_to_the_states_the_source_reaches(self):
        """A Washington publisher never reads Missouri's gazetteer."""
        sql = self._sql()
        assert "source_gazetteer_scope" in sql
        assert "np.state = sc.state" in sql

    def test_it_no_longer_filters_on_spacys_label(self):
        assert "entity_label" not in self._sql()

    def test_it_no_longer_reads_the_per_source_gazetteer(self):
        """`JOIN gazetteer g` was the circular evidence."""
        sql = self._sql()
        assert "JOIN gazetteer g" not in sql
        assert "addr:city" not in sql

    def test_it_matches_on_the_normalised_name(self):
        assert "np.name_norm = ae.entity_norm" in self._sql()

    def test_a_place_with_no_name_is_not_evidence(self):
        assert "np.place_name IS NOT NULL" in self._sql()

    def test_it_asks_for_one_article(self):
        session = _Session()
        institution_places(session, "a1")
        assert session.params[0] == {"id": "a1"}

    def test_it_returns_the_place_names(self):
        session = _Session([("Columbia",), ("Fulton",)])
        assert institution_places(session, "a1") == ["Columbia", "Fulton"]

    def test_no_evidence_is_an_empty_list(self):
        assert institution_places(_Session([]), "a1") == []


class TestTheBackfillAsksTheSameQuestion:
    """`reground` and the write path must agree on what counts, or the
    backfill deletes what enrichment would have kept."""

    def test_the_bulk_query_has_the_same_rules(self):
        from pathlib import Path

        source = Path("src/enrichment/repository.py").read_text()
        # The bulk statement itself, not the commentary around it.
        start = source.index('"SELECT DISTINCT ae.article_id, np.place_name "')
        bulk = source[start : source.index("cities_by_article[article_id].append")]
        assert "np.place_count = 1 " in bulk
        assert "source_gazetteer_scope" in bulk
        assert "np.state = sc.state" in bulk
        assert "entity_label" not in bulk
        assert "addr:city" not in bulk
