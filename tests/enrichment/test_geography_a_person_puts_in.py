"""`apply_manual_geography` without a database.

The integration tests that exercise this against real PostgreSQL are
skipped wherever one is not configured -- which is the default run, and
so the run the coverage floor measures. These cover the logic itself:
which articles are asked for, and what is written for each.
"""

from src.enrichment.repository import apply_manual_geography


class _Row:
    def __init__(self, article_id, geoid, level, is_point, already_primary):
        self.article_id = article_id
        self.geoid = geoid
        self.geoid_level = level
        self.is_point = is_point
        self.already_primary = already_primary


class _Result:
    def __init__(self, rows=(), rowcount=1):
        self._rows = list(rows)
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


class _Session:
    """Records the SQL it is given and answers the first query."""

    def __init__(self, rows=(), rowcount=1):
        self.rows = list(rows)
        self.rowcount = rowcount
        self.statements = []
        self.params = []
        self.committed = False

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        if len(self.statements) == 1:
            return _Result(self.rows)
        return _Result(rowcount=self.rowcount)

    def commit(self):
        self.committed = True


def test_it_writes_one_row_per_contribution():
    session = _Session(
        rows=[
            _Row("a1", "2943238", "place", True, False),
            _Row("a1", "2978910", "place", False, False),
        ]
    )
    result = apply_manual_geography(session)
    assert result == {"contributions": 2, "articles": 1, "written": 2}
    assert session.committed


def test_every_row_is_marked_human():
    """`source` is what keeps this honest: an analysis that wants to
    exclude human contributions can, and one that wants to count them
    can."""
    session = _Session(rows=[_Row("a1", "2943238", "place", True, False)])
    apply_manual_geography(session)
    insert = session.statements[1]
    assert "'human'" in insert
    # Additive: it runs outside enrichment and must not clear the set
    # `persist_outcome` wrote.
    assert "ON CONFLICT DO NOTHING" in insert
    assert "DELETE" not in insert.upper()


def test_a_human_centre_is_primary_only_where_nothing_else_claims_to_be():
    """Two primaries for one article is a contradiction rather than a
    disagreement worth keeping."""
    session = _Session(rows=[_Row("a1", "2943238", "place", True, True)])
    apply_manual_geography(session)
    assert session.params[1]["p"] is False

    session = _Session(rows=[_Row("a1", "2943238", "place", True, False)])
    apply_manual_geography(session)
    assert session.params[1]["p"] is True


def test_a_mention_is_never_primary():
    session = _Session(rows=[_Row("a1", "2943238", "place", False, False)])
    apply_manual_geography(session)
    assert session.params[1]["p"] is False


def test_a_dry_run_writes_nothing_and_commits_nothing():
    session = _Session(rows=[_Row("a1", "2943238", "place", True, False)])
    result = apply_manual_geography(session, dry_run=True)
    assert result["contributions"] == 1
    assert result["written"] == 0
    assert len(session.statements) == 1
    assert not session.committed


def test_the_filters_narrow_the_selection():
    """The same two a reviewer worked the queue by, so what was reviewed
    is what can be applied."""
    session = _Session()
    apply_manual_geography(session, dataset="Mizzou-Missouri-State")
    assert "d.slug = :dataset" in session.statements[0]
    assert session.params[0]["dataset"] == "Mizzou-Missouri-State"

    session = _Session()
    apply_manual_geography(session, since="2026-03-01")
    assert "a.publish_date >= :since" in session.statements[0]
    assert session.params[0]["since"] == "2026-03-01"

    session = _Session()
    apply_manual_geography(session)
    assert ":dataset" not in session.statements[0]
    assert ":since" not in session.statements[0]


def test_a_contribution_without_a_code_is_not_selected():
    """A row whose name never resolved has nothing to write."""
    session = _Session()
    apply_manual_geography(session)
    assert "m.geoid IS NOT NULL" in session.statements[0]


def test_nothing_to_apply_is_not_an_error():
    session = _Session(rows=[])
    assert apply_manual_geography(session) == {
        "contributions": 0,
        "articles": 0,
        "written": 0,
    }


def test_a_row_already_there_counts_as_nothing_written():
    """`ON CONFLICT DO NOTHING` reports rowcount 0, which is what makes
    re-running free -- it runs on a schedule beside a queue people are
    still working."""
    session = _Session(rows=[_Row("a1", "2943238", "place", True, False)], rowcount=0)
    assert apply_manual_geography(session)["written"] == 0
