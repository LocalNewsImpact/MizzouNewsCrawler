"""A licensee is not always the operator.

`sources.owner` holds who owns a publication, and for a newspaper that is also
who runs it. For television it often is not: KOLR and KODE are licensed to
Mission Broadcasting Inc and operated by Nexstar, a structure that exists
because the combination would otherwise exceed the FCC's ownership caps.

`cross_owner` was firing on six Mizzou bylines that cross those stations --
correctly, on a real ownership boundary, and uselessly, because the reviewer's
question is whether one person wrote them and the answer is yes: one newsroom
under two licences.
"""

from pathlib import Path

import pytest
from sqlalchemy import inspect

from src.models import Source
from src.services import byline_review as br

SERVICE = Path(__file__).resolve().parent.parent / "src/services/byline_review.py"
MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic/versions/f4a5b6c7d8e9_a_licensee_is_not_always_the_operator.py"
)


class TestTheColumn:
    def test_a_source_can_name_its_operator(self):
        assert "operator" in inspect(Source).columns

    def test_it_is_optional(self):
        """Null for almost everything -- a newspaper's owner runs it."""
        assert inspect(Source).columns["operator"].nullable is True

    def test_the_licensee_keeps_its_own_column(self):
        """`owner` is not repurposed. Mission Broadcasting really does own
        those licences, and saying otherwise to quieten a signal would be
        writing something false into a column named `owner`."""
        assert "owner" in inspect(Source).columns

    def test_the_migration_chains_from_the_stale_decision_columns(self):
        body = MIGRATION.read_text()
        assert 'down_revision = "e3f4a5b6c7d8"' in body
        assert "nullable=True" in body

    def test_the_downgrade_removes_it(self):
        body = MIGRATION.read_text()
        assert "drop_column" in body[body.index("def downgrade") :]


class TestTheSignalGroupsOnTheOperator:
    """Two stations under one operator are one newsroom whoever holds the
    licences."""

    def test_the_operator_is_preferred_over_the_owner(self):
        source = SERVICE.read_text()
        assert "coalesce(nullif(trim(s.operator), '')" in source

    def test_the_owner_is_still_the_fallback(self):
        """Almost every source has no operator, and must group exactly as it
        did before."""
        source = SERVICE.read_text()
        assert "nullif(trim(s.owner), ''), '(unknown)') AS owner," in source

    def test_every_query_that_reads_owners_agrees(self):
        """Three queries read the owner for grouping. One left behind would
        make the same byline cross ownership in one report and not in
        another."""
        source = SERVICE.read_text()
        assert source.count("coalesce(nullif(trim(s.operator), '')") == 3
        assert (
            "coalesce(nullif(trim(s.owner), ''), '(unknown)') AS owner," not in source
        )


class TestWhatTheSignalDoesWithIt:
    def _row(self, owners):
        return br.BylineRow(
            raw="A Reporter",
            articles=3,
            hosts=("a.example", "b.example"),
            owners=tuple(owners),
        )

    def test_one_operator_across_two_licences_is_not_cross_owner(self):
        """What the column is for. Both rows arrive carrying the operator,
        because the query resolved it before the signal ever saw them."""
        signals = br.signals_for(self._row(["Nexstar Media Group"]), {})
        assert br.CROSS_OWNER not in signals

    def test_genuinely_unrelated_owners_still_are(self):
        signals = br.signals_for(self._row(["Gray Television", "Tegna Inc"]), {})
        assert br.CROSS_OWNER in signals

    def test_one_owner_is_never_cross_owner(self):
        assert br.CROSS_OWNER not in br.signals_for(self._row(["Gray Television"]), {})


@pytest.mark.parametrize(
    "operator,owner,expected",
    [
        ("Nexstar Media Group", "Mission Broadcasting Inc", "Nexstar Media Group"),
        ("", "Gray Television", "Gray Television"),
        (None, "Gray Television", "Gray Television"),
        (None, None, "(unknown)"),
    ],
)
def test_the_coalesce_resolves_as_written(operator, owner, expected):
    """The SQL in Python, so the precedence is pinned rather than read."""
    resolved = (operator or "").strip() or (owner or "").strip() or "(unknown)"
    assert resolved == expected
