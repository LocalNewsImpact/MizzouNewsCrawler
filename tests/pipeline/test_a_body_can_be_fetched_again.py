"""Rewinding an article far enough that its URL is fetched again.

Extraction refuses twice over: its batch query requires
`candidate_links.status = 'article'` AND no article row, and
`ARTICLE_INSERT_SQL` ends `ON CONFLICT DO NOTHING`. A rewind that satisfies
only the first refusal fetches the page, pays for the request and discards the
body -- and the conflict accounting reads that as "the article exists under
another link", so it looks like it worked.
"""

from __future__ import annotations

import json

import pytest

from src.pipeline import refetch


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = len(self._rows)

    def mappings(self):
        return iter(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Session:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _Result(self.answers.pop(0)) if self.answers else _Result()

    def commit(self):
        self.commits += 1


def _article(article_id="a1", link_status="paywall"):
    return {
        "id": article_id,
        "candidate_link_id": f"link-{article_id}",
        "link_status": link_status,
        "url": f"https://example.com/{article_id}",
    }


class TestTheRewindIsAccountable:
    def test_a_rewind_without_an_author_is_refused(self):
        """These rows carry a measurement somebody may later question. A body
        replaced with no record of who asked is indistinguishable from a body
        that was always wrong."""
        with pytest.raises(refetch.Refused):
            refetch.mark(_Session(), ["a1"], by="", reason="paywall teaser")

    def test_a_rewind_without_a_reason_is_refused(self):
        with pytest.raises(refetch.Refused):
            refetch.mark(_Session(), ["a1"], by="damon", reason="  ")

    def test_an_empty_id_list_does_nothing_rather_than_everything(self):
        session = _Session()
        counts = refetch.mark(session, [], by="damon", reason="x")
        assert counts == {"requested": 0, "marked": 0, "already": 0, "missing": 0}
        assert session.statements == []


class TestWhatARewindWrites:
    def test_it_sets_the_link_to_refetch_and_records_the_previous_status(self):
        """The previous status is the only way back: a fetch that fails leaves
        the link at `refetch` with nothing to say what it was."""
        session = _Session(answers=[[_article(link_status="paywall")]])
        counts = refetch.mark(
            session, ["a1"], by="damon", reason="no body; BLOX auth wired"
        )
        assert counts["marked"] == 1
        note = json.loads(next(p["note"] for p in session.params if p and "note" in p))
        assert note["previous_link_status"] == "paywall"
        assert note["by"] == "damon"
        assert note["reason"] == "no body; BLOX auth wired"
        link_param = next(p for p in session.params if p and "link_id" in p)
        assert link_param["refetch"] == "refetch"
        assert session.commits == 1

    def test_it_leaves_labels_and_enrichment_alone(self):
        """A body that changes invalidates what was concluded from it, but
        invalidating that is the classify and enrich stages' job, reached
        afterwards. Deciding here would re-litigate verdicts before knowing
        whether the fetch even succeeded."""
        session = _Session(answers=[[_article()]])
        refetch.mark(session, ["a1"], by="damon", reason="teaser")
        written = " ".join(session.statements).lower()
        for table in (
            "article_labels",
            "article_enrichment",
            "article_places",
            "article_geoids",
            "article_entities",
        ):
            assert table not in written
        assert "primary_label" not in written

    def test_an_already_rewound_article_is_counted_not_rewritten(self):
        """Otherwise a second run overwrites the original reason and the
        previous status with `refetch`, losing the way back."""
        session = _Session(answers=[[_article(link_status="refetch")]])
        counts = refetch.mark(session, ["a1"], by="damon", reason="teaser")
        assert counts == {
            "requested": 1,
            "marked": 0,
            "already": 1,
            "missing": 0,
            "missing_ids": [],
        }
        assert not any(p and "note" in p for p in session.params)

    def test_an_unknown_id_is_reported_rather_than_silently_dropped(self):
        session = _Session(answers=[[_article()]])
        counts = refetch.mark(session, ["a1", "nope"], by="d", reason="r")
        assert counts["missing"] == 1
        assert counts["missing_ids"] == ["nope"]

    def test_the_dry_run_writes_nothing(self):
        session = _Session(answers=[[_article()]])
        counts = refetch.mark(
            session, ["a1"], by="damon", reason="teaser", dry_run=True
        )
        assert counts["marked"] == 1
        assert session.commits == 0
        assert not any(p and "note" in p for p in session.params)


class TestTheListingAcceptsTheNameYouHave:
    """`--dataset WSU-Washington-State` is what a person types. Matching that
    against `articles.dataset_id`, which holds a UUID, found nothing and the
    command printed "nothing is waiting to be fetched again" over a queue with
    work in it -- a wrong answer indistinguishable from the right one."""

    def test_a_slug_is_matched_as_well_as_an_id(self):
        session = _Session(answers=[[]])
        refetch.marked(session, "WSU-Washington-State")
        sql = session.statements[0]
        assert "d.slug = CAST(:dataset AS varchar)" in sql
        assert "a.dataset_id = CAST(:dataset AS varchar)" in sql
        assert "LEFT JOIN datasets" in sql

    def test_no_dataset_lists_every_rewound_article(self):
        session = _Session(answers=[[]])
        refetch.marked(session)
        assert session.params[0]["dataset"] is None


class TestGivingUp:
    def test_clear_restores_the_status_the_link_had(self):
        """A page with no prose, or a login that cannot be made to work: the
        link has to stop claiming it owes a fetch."""
        session = _Session(answers=[[("a1",)]])
        refetch.clear(session, ["a1"])
        restore = next(s for s in session.statements if "UPDATE candidate_links" in s)
        assert "previous_link_status" in restore
        assert "'extracted'" in restore  # the fallback when none was recorded
        assert session.commits == 1

    def test_clearing_nothing_touches_nothing(self):
        session = _Session()
        assert refetch.clear(session, []) == 0
        assert session.statements == []


class TestExtractionActuallySeesThem:
    """The rewind is worthless if the selectors still exclude the link and the
    insert still discards the body."""

    def _extraction_source(self) -> str:
        from pathlib import Path

        return Path("src/cli/commands/extraction.py").read_text()

    def test_both_selectors_admit_a_refetch_link(self):
        source = self._extraction_source()
        assert source.count("cl.status IN ('article', 'refetch')") == 2

    def test_an_existing_article_disqualifies_a_link_unless_it_is_a_refetch(self):
        """The NOT EXISTS guard must survive for every other status: without it
        ordinary extraction re-fetches finished work every night."""
        source = self._extraction_source()
        assert source.count("cl.status = 'refetch' OR NOT EXISTS") == 2

    def test_a_refetch_replaces_the_body_instead_of_inserting(self):
        source = self._extraction_source()
        assert "ARTICLE_REFETCH_SQL" in source
        assert (
            "ON CONFLICT"
            not in source.split("ARTICLE_REFETCH_SQL")[1].split("ARTICLE_FOR_LINK_SQL")[
                0
            ]
        )

    def test_the_replacement_is_the_only_statement_that_writes_content(self):
        """`ARTICLE_UPDATE_SQL` omits `content` to make the canonical capture
        immutable by construction. Keeping the replacement separate is what
        preserves that everywhere except the path a person asked for by name."""
        source = self._extraction_source()
        update = source.split("ARTICLE_UPDATE_SQL = text(")[1].split(")")[0]
        assert "content" not in update


class TestTheFiltersCannotSilentlyVanish:
    """Three filters are injected into the candidate-link query by text
    substitution, and `str.replace` that matches nothing reports success. An
    extraction run whose dataset filter vanished takes every dataset."""

    def test_adding_a_filter_puts_it_after_the_status_clause(self):
        from src.cli.commands import extraction

        out = extraction._inject_filter(
            extraction.LINK_STATUS_CLAUSE, "AND cl.dataset_id = :dataset"
        )
        assert out.startswith(extraction.LINK_STATUS_CLAUSE)
        assert "AND cl.dataset_id = :dataset" in out

    def test_a_query_without_the_anchor_raises_rather_than_passing_through(self):
        from src.cli.commands import extraction

        with pytest.raises(RuntimeError, match="no longer contains"):
            extraction._inject_filter(
                "SELECT 1 FROM candidate_links", "AND cl.dataset_id = :dataset"
            )

    def test_the_anchor_is_built_from_the_status_the_rewind_writes(self):
        """Two spellings of `refetch` would be two behaviours: the rewind
        writing one and the selector reading the other."""
        from src.cli.commands import extraction

        assert refetch.REFETCH in extraction.LINK_STATUS_CLAUSE
        assert extraction.REFETCH == refetch.REFETCH
