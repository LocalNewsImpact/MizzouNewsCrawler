"""`reground_stored` without a database.

The gate in `grounding` only protects what is enriched from now on. This
is the half that cleans the 20,521 rows already written, 97.4% of which
are March -- the month BigQuery treats as authoritative, which is why the
dry run exists and why it is the documented first step.

Fake-session tests for the same reason as `test_geography_a_person_puts_in`:
the PostgreSQL integration run is skipped by default, and the default run
is what the coverage floor measures.
"""

from __future__ import annotations

from src.enrichment.repository import reground_stored

COLUMBIA, BOONE, MEXICO = "2915670", "29019", "2947704"


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


#: Queries `reground_stored` runs before it writes anything: the article
#: list, then per chunk the geoid rows and the institution cities.
SETUP_QUERIES = 3


class _Session:
    """Answers the setup queries, then records every write it is handed."""

    def __init__(self, articles=(), geoid_rows=(), cities=()):
        self._articles = list(articles)
        self._geoid_rows = list(geoid_rows)
        self._cities = list(cities)
        self.statements: list[str] = []
        self.params: list[dict | None] = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        if len(self.statements) == 1:
            return _Result(self._articles)
        if len(self.statements) == 2:
            return _Result(self._geoid_rows)
        if len(self.statements) == SETUP_QUERIES:
            return _Result(self._cities)
        return _Result()

    def commit(self):
        self.commits += 1

    def writes(self):
        return list(self.statements[SETUP_QUERIES:])


UNGROUNDED = [
    ("a1", "A graduation in Mexico, Missouri.", "Mexico high senior", "Mexico")
]
UNGROUNDED_ROWS = [
    ("a1", COLUMBIA, "place", True, "point"),
    ("a1", BOONE, "county", False, "county_rollup"),
]


class TestTheDryRunWritesNothing:
    """The March corpus is authoritative. A change to it is approved from
    a report, not discovered afterwards."""

    def test_it_counts_what_it_would_remove(self):
        session = _Session(UNGROUNDED, UNGROUNDED_ROWS)
        result = reground_stored(session, dry_run=True)
        assert result["articles"] == 1
        assert result["articles_changed"] == 1
        assert result["places_dropped"] == 1
        assert result["counties_dropped"] == 1
        assert result["points_cleared"] == 1

    def test_it_issues_no_write_and_no_commit(self):
        session = _Session(UNGROUNDED, UNGROUNDED_ROWS)
        reground_stored(session, dry_run=True)
        assert session.writes() == []
        assert session.commits == 0


class TestApplyingIt:
    def test_the_dropped_codes_are_deleted(self):
        session = _Session(UNGROUNDED, UNGROUNDED_ROWS)
        reground_stored(session, dry_run=False)
        deletes = [
            (sql, params)
            for sql, params in zip(session.statements, session.params, strict=False)
            if sql.strip().upper().startswith("DELETE")
        ]
        assert len(deletes) == 1
        assert set(deletes[0][1]["codes"]) == {COLUMBIA, BOONE}

    def test_a_person_is_never_deleted(self):
        """`source <> 'human'` in the statement itself, not merely in the
        caller's arithmetic: a contribution is not re-litigated by a
        heuristic even if one day it reaches the drop list by accident."""
        session = _Session(UNGROUNDED, UNGROUNDED_ROWS)
        reground_stored(session, dry_run=False)
        delete = next(
            s for s in session.statements if s.strip().upper().startswith("DELETE")
        )
        assert "source <> 'human'" in delete

    def test_the_flat_column_is_rewritten(self):
        session = _Session(UNGROUNDED, UNGROUNDED_ROWS)
        reground_stored(session, dry_run=False)
        update = next(
            params
            for sql, params in zip(session.statements, session.params, strict=False)
            if "UPDATE article_enrichment" in sql
        )
        assert update["geoids"] == "[]"

    def test_an_unsupported_point_takes_every_point_column_with_it(self):
        """A dot on the map with nothing behind it is worse than no dot:
        clearing `point_place` while leaving `point_lat` set still draws."""
        session = _Session(UNGROUNDED, UNGROUNDED_ROWS)
        reground_stored(session, dry_run=False)
        update = next(s for s in session.statements if "UPDATE article_enrichment" in s)
        for column in (
            "point_place",
            "point_geoid",
            "point_geoid_level",
            "point_lat",
            "point_lon",
            "point_method",
        ):
            assert f"{column} = NULL" in update
        assert "geo_skip_reason = :reason" in update

    def test_it_commits(self):
        session = _Session(UNGROUNDED, UNGROUNDED_ROWS)
        reground_stored(session, dry_run=False)
        assert session.commits == 1


class TestAnArticleItSupportsIsLeftAlone:
    def test_nothing_is_dropped_and_nothing_written(self):
        session = _Session(
            [("a1", "The council met in Columbia on Tuesday.", None, "Mexico")],
            UNGROUNDED_ROWS,
        )
        result = reground_stored(session, dry_run=False)
        assert result["articles_changed"] == 0
        assert session.writes() == []

    def test_an_article_with_no_codes_is_skipped(self):
        session = _Session([("a1", "Anything.", None, None)], [])
        result = reground_stored(session, dry_run=True)
        assert result["articles_changed"] == 0


class TestScoping:
    def test_no_articles_short_circuits(self):
        session = _Session([], [])
        result = reground_stored(session, dry_run=True)
        assert result == {
            "articles": 0,
            "articles_changed": 0,
            "places_dropped": 0,
            "counties_dropped": 0,
            "points_cleared": 0,
            "unverifiable": 0,
        }
        assert len(session.statements) == 1

    def test_a_window_reaches_the_query(self):
        session = _Session([], [])
        reground_stored(session, since="2026-03-01", until="2026-04-01", dry_run=True)
        sql, params = session.statements[0], session.params[0]
        assert "a.publish_date >= :since" in sql
        assert "a.publish_date < :until" in sql
        assert params["since"] == "2026-03-01"

    def test_a_dataset_is_resolved_by_slug(self):
        session = _Session([], [])
        reground_stored(session, dataset="mizzou-missouri", dry_run=True)
        assert "SELECT id FROM datasets WHERE slug = :slug" in session.statements[0]
        assert session.params[0]["slug"] == "mizzou-missouri"

    def test_a_limit_reaches_the_query(self):
        session = _Session([], [])
        reground_stored(session, limit=25, dry_run=True)
        assert "LIMIT 25" in session.statements[0]

    def test_it_reads_only_articles_that_have_geography(self):
        """Every enrichment row would otherwise be fetched with its full
        body -- 20,521 of them -- to decide nothing."""
        session = _Session([], [])
        reground_stored(session, dry_run=True)
        assert "EXISTS (SELECT 1 FROM article_geoids" in session.statements[0]
