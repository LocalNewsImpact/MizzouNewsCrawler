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

    def test_a_replaced_body_stops_claiming_it_was_imported(self):
        """`extraction_version` is NULL on a fresh extraction, so
        `manual-import-v1` is what marks a body the spreadsheet supplied.
        Keeping it through a refetch made four crawled articles count as never
        crawled, and "which hosts can we fetch?" answered with the notebook's
        text for all of them."""
        source = self._extraction_source()
        refetch_sql = source.split("ARTICLE_REFETCH_SQL = text(")[1].split('")')[0]
        assert "extraction_version = NULL" in refetch_sql

    def test_the_replacement_is_the_only_statement_that_writes_raw(self):
        """`ARTICLE_UPDATE_SQL` omits `raw` to make the canonical capture
        immutable by construction. Keeping the replacement separate is what
        preserves that everywhere except the path a person asked for by name."""
        source = self._extraction_source()
        update = source.split("ARTICLE_UPDATE_SQL = text(")[1].split(")")[0]
        assert "raw" not in update


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


class TestARowStopsAsking:
    """Four links sat open in `pipeline_rework` from 2026-09-14 on hosts where
    Selenium fails every time. The queue served them, all failed, their domains
    entered cooldown, and the step waited 30s and asked again for two hours
    until the pod deadline killed the workflow -- twice, neither run reaching
    classify or enrich."""

    def test_a_spent_row_is_not_served_again(self):
        from src.pipeline import rework

        session = _Session(answers=[[]])
        rework.links_to_fetch(session)
        sql = session.statements[0]
        assert "coalesce(r.attempts, 0) < :max_attempts" in sql
        assert session.params[0]["max_attempts"] == rework.MAX_ATTEMPTS

    def test_taking_a_row_spends_an_attempt(self):
        from src.pipeline import rework

        session = _Session()
        rework.count_attempt(session, ["l1", "l2"])
        assert any(
            "attempts = coalesce(attempts, 0) + 1" in s for s in session.statements
        )
        assert session.commits == 1

    def test_a_row_at_the_limit_is_closed_with_a_reason(self):
        """Otherwise it is excluded from selection but never settles, and the
        'anything owed' count reports work nobody will ever do."""
        from src.pipeline import rework

        session = _Session(answers=[[], [("l1",)]])
        abandoned = rework.count_attempt(session, ["l1"])
        assert abandoned == {"l1"}
        close = next(s for s in session.statements if "outcome = :outcome" in s)
        assert "coalesce(attempts, 0) >= :max_attempts" in close
        assert any(p and p.get("outcome") == rework.ABANDONED for p in session.params)

    def test_it_returns_ids_rather_than_making_the_caller_re_read(self):
        """`_process_batch` asks `_links_owed_a_fetch` exactly once and the
        direct path reuses that set, so re-reading it would be a second query
        for an answer already held -- and a test already pins that count."""
        import inspect

        from src.cli.commands import extraction

        body = inspect.getsource(extraction._process_batch)
        assert body.count("_links_owed_a_fetch(session)") == 1
        assert "if i not in abandoned" in body

    def test_the_outcome_matches_what_enrichment_calls_it(self):
        """One answer to "why did this stop" across stages."""
        from src.pipeline import rework

        assert rework.ABANDONED == "failed_max_attempts"

    def test_counting_nothing_touches_nothing(self):
        from src.pipeline import rework

        session = _Session()
        assert rework.count_attempt(session, []) == set()
        assert session.statements == []


class TestAReworkRunStopsWaiting:
    def test_the_poll_limit_is_bounded_and_overridable(self):
        from src.cli.commands import extraction

        assert extraction.REWORK_EMPTY_POLL_LIMIT >= 1
        assert extraction.REWORK_EMPTY_POLL_LIMIT <= 10

    def test_only_a_rework_run_gives_up_on_a_cooldown(self):
        """The pipeline's queue is fed continuously, so waiting there is right:
        a cooldown passes and more work arrives. Breaking out of that loop
        unconditionally would stop ordinary extraction on the first quiet poll."""
        from pathlib import Path

        source = Path("src/cli/commands/extraction.py").read_text()
        guard = "if is_rework and empty_polls >= REWORK_EMPTY_POLL_LIMIT:"
        assert guard in source
        # and the streak resets when a batch does produce work
        assert "if articles_processed > 0:\n                empty_polls = 0" in source


class TestAFailedRefetchGivesUp:
    """A rewound link must not owe work forever. Housekeeping bounds its rows
    with `rework.count_attempt`; a rewind that is not in `pipeline_rework`
    -- the 226 shared-body rows never were -- had no bound at all, and a fetch
    that kept failing was retried every run."""

    def test_the_status_it_gives_up_to_is_selected_by_no_stage(self):
        assert refetch.TEXT_UNAVAILABLE == "text_unavailable"
        for selected in (
            ("cleaned", "local"),
            ("labeled",),
            ("enriched", "enrichment_skipped"),
        ):
            assert refetch.TEXT_UNAVAILABLE not in selected

    def test_a_try_below_the_bound_gives_up_on_nothing(self):
        session = _Session(answers=[[("l1", 1), ("l2", 2)]])
        assert refetch.spend_attempt(session, ["l1", "l2"]) == set()
        assert len(session.statements) == 1
        assert "'{refetch,attempts}'" in session.statements[0]
        assert session.commits == 0, "a commit would release SKIP LOCKED rows mid-batch"

    def test_the_bound_is_the_one_housekeeping_uses(self):
        from src.pipeline.rework import ABANDONED, MAX_ATTEMPTS

        session = _Session(answers=[[("l1", MAX_ATTEMPTS), ("l2", 1)]])
        assert refetch.spend_attempt(session, ["l1", "l2"]) == {"l1"}
        gave_up = [
            s for s in session.statements if "UPDATE articles" in s and "outcome" in s
        ]
        assert len(gave_up) == 1
        assert session.params[1]["status"] == refetch.TEXT_UNAVAILABLE
        assert session.params[1]["outcome"] == ABANDONED
        assert session.params[1]["link_ids"] == ["l1"]

    def test_giving_up_keeps_the_record_and_puts_the_link_back(self):
        session = _Session()
        refetch.give_up(session, ["l1"], outcome="404")
        article, link = session.statements
        assert "SET status = :status" in article and "'{refetch,outcome}'" in article
        for column in ("title", "author", "publish_date", "text"):
            assert f"{column} =" not in article, "the record is what survives"
        assert "UPDATE candidate_links" in link
        assert "previous_link_status" in link and "cl.status = :refetch" in link

    def test_nothing_in_touches_nothing(self):
        session = _Session()
        assert refetch.spend_attempt(session, []) == set()
        assert refetch.give_up(session, [], outcome="404") == 0
        assert session.statements == []


class TestExtractionGivesUpOnTheRightPaths:
    def _source(self) -> str:
        from pathlib import Path

        return Path("src/cli/commands/extraction.py").read_text()

    def test_tries_are_spent_on_the_batch_after_it_is_selected(self):
        source = self._source()
        assert source.index("spend_attempt(session, refetch_links)") < source.index(
            "for row in rows:"
        )

    def test_both_404_paths_give_up_with_the_reason(self):
        assert (
            self._source().count('give_up(session, [str(url_id)], outcome="404")') == 2
        )

    def test_furniture_on_a_rewound_record_is_text_unavailable_not_not_article(self):
        source = self._source()
        assert 'if status == REFETCH and article_status == "not_article":' in source
        assert "article_status = TEXT_UNAVAILABLE" in source
