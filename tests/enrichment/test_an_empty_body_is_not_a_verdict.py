"""An article with no body is not "not news". It is unenrichable.

The model reads `a.text`, the processed body. (The free paywall pre-check
alone reads `a.raw`, the capture its thresholds were measured against.) An
article whose body is empty was being sent to the model anyway, which
answered `not_news` -- about nothing at all -- and the record was excluded
for a property of the row rather than anything about the story.

Measured on 2026-09-14, when the model still read the capture: 84 articles
had an empty capture with the body intact in `text`, all of them
`manual_art_` records the March reconciliation created without writing one.
59 of one housekeeping run's 64 `not_news` refusals were these. One was a
fatal motorcycle crash in Doolittle, Missouri, with 2,211 characters of
story the gate never saw and no geography recorded -- while the same story,
captured normally, carried Phelps County.

The refusal is now made at selection, by name, where it costs nothing and
says what is actually wrong.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.enrichment import repository

STORY = (
    "A Doolittle man died Friday when his motorcycle left Interstate 44 near "
    "the Phelps County line. The Missouri State Highway Patrol said the crash "
    "happened shortly before noon. "
) * 4


def _row(body, article_id="a1", raw=None):
    return SimpleNamespace(
        id=article_id,
        title="Doolittle man killed in motorcycle crash",
        text=body,
        raw=body if raw is None else raw,
        metadata=None,
        status="labeled",
        wire_check_status="complete",
        enrichment_attempts=0,
        dataset_slug="ds",
        publication_city="Columbia",
        publication_state="MO",
        reviewed_kind=None,
    )


def _select(rows, ids):
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = rows
    return repository.select_by_ids(session, ids, max_attempts=3)


class TestAnEmptyBodyIsRejectedNotJudged:
    @pytest.mark.parametrize("empty", [None, "", "   ", "\n\t "])
    def test_it_is_rejected_by_name(self, empty):
        """Not a candidate, and the reason says what is wrong with the ROW --
        so a person reading the run's accounting sees "no text", not a
        verdict about the journalism."""
        report = _select([_row(empty)], ["a1"])
        assert report.candidates == []
        assert "a1" in report.rejected
        assert "text" in report.rejected["a1"].lower()

    def test_it_never_reaches_the_model(self):
        """THE COST. Every one of these was a paid call that returned a
        verdict about an empty string, and the verdict excluded the article."""
        report = _select([_row("")], ["a1"])
        assert report.candidates == [], "an empty body must not be enriched"

    def test_a_real_body_still_passes(self):
        report = _select([_row(STORY)], ["a1"])
        assert [c.id for c in report.candidates] == ["a1"]
        assert report.rejected == {}

    def test_a_capture_does_not_rescue_an_empty_text(self):
        """The model reads the processed body. A row whose story is only in
        the capture is rejected rather than silently read from `raw`, so the
        fix is to process it into `text`."""
        report = _select([_row("", raw=STORY)], ["a1"])
        assert report.candidates == []
        assert "a1" in report.rejected

    def test_one_empty_body_does_not_reject_the_others(self):
        rows = [_row(STORY, "good"), _row("", "empty"), _row(STORY, "also_good")]
        report = _select(rows, ["good", "empty", "also_good"])
        assert sorted(c.id for c in report.candidates) == ["also_good", "good"]
        assert list(report.rejected) == ["empty"]


class TestTheSelectionQueriesAgree:
    """The guard has to hold on every path that feeds the model, not just the
    one the rework step happens to use. `select_by_ids` rejects by name;
    the two batch queries exclude in SQL."""

    @pytest.mark.parametrize("sql", ["_CANDIDATE_SQL", "_REPROCESS_SQL"])
    def test_the_batch_queries_exclude_an_empty_body(self, sql):
        assert "coalesce(a.text, '') <> ''" in str(getattr(repository, sql))

    def test_the_queries_read_text_and_keep_the_capture_for_the_gate(self):
        """`text` is what the model reads; `raw` is selected beside it for the
        free paywall pre-check, whose thresholds were measured on `raw`."""
        for sql in ("_CANDIDATE_SQL", "_REPROCESS_SQL"):
            body = str(getattr(repository, sql))
            assert "a.text, a.raw" in body
            assert "coalesce(a.raw" not in body.lower()
