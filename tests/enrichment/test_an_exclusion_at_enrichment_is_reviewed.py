"""An exclusion decided at enrichment is held for a person, not written.

Enrichment is the last step before export and the only one where a model
reads the body. It finds what earlier stages missed, and it is wrong often
enough that acting unseen costs real stories: of 75 articles the model
called "international" on 2026-09-13, 50 carried a local byline.

Two rules, tested at the seams rather than at the function:

- Anything enrichment decides that would stop a record being exportable
  -- `not_article`, `out_of_scope` -- is held (`in_review`, with the
  claim, the stage and the status to restore) and the console asks. A
  paywall stub is not held: it stays exportable with its CIN label.
- A claim a person has answered is not raised again. The gate reads the
  answer before refusing, or the record is held, released by a reviewer,
  and held again by the next run: a loop with a person in it -- which
  is also how a human accept was silently overwritten by `not_news`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from lnic_contracts import review_note as contract

from src.enrichment import hold, repository
from src.enrichment.gate import BOILERPLATE_SKIP_REASON, NOT_NEWS_SKIP_REASON
from src.enrichment.orchestrator import PAYWALL_RULE_SKIP_REASON
from src.enrichment.profiles import Profile
from src.enrichment.repository import _rows_to_articles
from src.enrichment.types import ArticleInput, EnrichmentOutcome, StepResult

from .test_orchestrator import FULL, meta, ok, run

STORY = (
    "The council met Tuesday to review the budget. Members voted to fund the "
    "water main replacement on Third Street. The measure passed four to one "
    "after an hour of public comment. Residents asked about the schedule. "
    "The city engineer said work would begin in the spring. "
) * 3

EXCLUDING = Profile(
    version=3,
    content_gate=True,
    scope=True,
    places=True,
    geocode=False,
    people=False,
    organizations=False,
    metadata_presets=(),
    export_exclude_scopes=("international",),
)


def article(answered=frozenset()):
    return ArticleInput("a1", "T", STORY, "ds", "Columbia", answered=answered)


def answered_on(metadata, claim, decision="restore"):
    """What the console writes when a reviewer rules on an enrichment hold.
    `restore` overrules the gate ("it is a real story"); `accept` confirms."""
    return contract.record_decision(
        metadata,
        contract.build_decision(claim=claim, stage=hold.STAGE, decision=decision),
    )


# ---------------------------------------------------------------------------
# Which outcomes are held.
# ---------------------------------------------------------------------------


class TestWhatIsHeld:
    def test_an_exclusion_is_held(self):
        assert hold.should_hold("not_article")
        assert hold.should_hold("out_of_scope")

    def test_an_exportable_outcome_is_not(self):
        """A paywall stub keeps its CIN label and stays in the export.
        Nothing about it needs a person."""
        for status in ("enriched", "enrichment_skipped", "labeled"):
            assert not hold.should_hold(status), status

    def test_the_held_set_is_exactly_the_non_exportable_outcomes(self):
        """The rule in one line: held if and only if it would leave the
        export. Ties the two definitions together so they cannot drift."""
        for status in hold.HELD_STATUSES:
            assert status not in repository.EXPORTABLE_STATUSES
        for status in repository.EXPORTABLE_STATUSES:
            assert status not in hold.HELD_STATUSES


# ---------------------------------------------------------------------------
# Seam: persist. The exclusion is written as a hold, the finding is kept.
# ---------------------------------------------------------------------------


def _persist(outcome, current_metadata=None):
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = (
        json.dumps(current_metadata) if current_metadata is not None else None
    )
    writes = []
    original = session.execute

    def capture(stmt, params=None):
        writes.append((str(stmt), params or {}))
        return original(stmt, params)

    session.execute = capture
    repository.persist_outcome(
        session,
        article(),
        outcome,
        profile=EXCLUDING,
        model="m",
        backfield_commit="c",
        prompt_versions={},
    )
    status_writes = [p for s, p in writes if "UPDATE articles SET status" in s]
    assert status_writes, "no status was written"
    return status_writes[-1], writes


def _outcome(status, skip_reason):
    return EnrichmentOutcome(
        article_id="a1",
        status=status,
        skip_reason=skip_reason,
        steps_applied=["content_gate"],
        results=[
            StepResult(
                "content_gate", True, {"verdict": "x"}, None, 10, 5, Decimal("0.001")
            )
        ],
        total_cost_usd=Decimal("0.001"),
    )


class TestPersistHoldsInsteadOfExcluding:
    def test_not_article_from_the_gate_is_held(self):
        written, _ = _persist(_outcome("not_article", NOT_NEWS_SKIP_REASON))
        assert written["status"] == contract.IN_REVIEW
        note = json.loads(written["meta"])[contract.METADATA_KEY]
        assert note["claim"] == NOT_NEWS_SKIP_REASON
        assert note["stage"] == hold.STAGE
        # The exclusion the gate wanted: a reviewer's ACCEPT restores it.
        assert note["status_before"] == "not_article"

    def test_out_of_scope_is_held(self):
        written, _ = _persist(_outcome("out_of_scope", "scope_excluded_international"))
        assert written["status"] == contract.IN_REVIEW
        note = json.loads(written["meta"])[contract.METADATA_KEY]
        assert note["claim"] == "scope_excluded_international"
        assert note["status_before"] == "out_of_scope"

    def test_a_paywall_stub_is_written_as_decided(self):
        written, _ = _persist(_outcome("enrichment_skipped", PAYWALL_RULE_SKIP_REASON))
        assert written["status"] == "enrichment_skipped"
        assert "meta" not in written

    def test_the_finding_is_still_recorded_when_held(self):
        """The enrichment row says what the gate found, whichever way the
        reviewer rules. Holding is not forgetting."""
        _, writes = _persist(_outcome("not_article", NOT_NEWS_SKIP_REASON))
        enrichment_writes = [p for s, p in writes if "article_enrichment" in s]
        assert enrichment_writes, "the finding was not written"

    def test_the_note_is_readable_by_the_console(self):
        """Built by the contract, so the console can form the question and
        restore the status. A note it cannot read strands the row."""
        written, _ = _persist(_outcome("not_article", BOILERPLATE_SKIP_REASON))
        metadata = json.loads(written["meta"])
        assert contract.is_readable(metadata[contract.METADATA_KEY])

    def test_earlier_decisions_on_the_article_survive_a_hold(self):
        """The hold replaces the NOTE, not the record of what people have
        already answered."""
        prior = answered_on({}, "some_other_claim")
        written, _ = _persist(
            _outcome("not_article", NOT_NEWS_SKIP_REASON), current_metadata=prior
        )
        metadata = json.loads(written["meta"])
        assert contract.decision_for(
            metadata, claim="some_other_claim", stage=hold.STAGE
        )


# ---------------------------------------------------------------------------
# Seam: the gate honours an answer.
# ---------------------------------------------------------------------------


class TestAnAnsweredClaimIsNotRaisedAgain:
    def test_not_news_overruled_by_a_person_goes_through(self):
        """THE LOOP, AND THE OVERRIDE. Without this the article is held,
        released by a reviewer as a story, and held again by the next run;
        and before holds existed, `not_news` simply overwrote the reviewer's
        accept, with nobody told."""
        result, stub = run(
            FULL,
            article=article(answered=frozenset({NOT_NEWS_SKIP_REASON})),
            content_gate=ok("content_gate", {"verdict": "not_news", "reason": ""}),
        )
        assert result.status == "enriched"
        assert "scope" in stub.calls, "the answered refusal did not stop the run"

    def test_not_news_with_no_answer_is_still_refused(self):
        result, _ = run(
            FULL,
            article=article(),
            content_gate=ok("content_gate", {"verdict": "not_news", "reason": ""}),
        )
        assert result.status == "not_article"
        assert result.skip_reason == NOT_NEWS_SKIP_REASON

    def test_a_boilerplate_refusal_answered_goes_through(self):
        body = (
            "cookies consent privacy policy vendor list opt out advertising partners "
            + STORY
        )
        held = ArticleInput("a1", "T", body, "ds", "Columbia")
        assert run(FULL, article=held)[0].skip_reason == BOILERPLATE_SKIP_REASON
        overruled = ArticleInput(
            "a1",
            "T",
            body,
            "ds",
            "Columbia",
            answered=frozenset({BOILERPLATE_SKIP_REASON}),
        )
        result, stub = run(FULL, article=overruled)
        assert result.skip_reason != BOILERPLATE_SKIP_REASON
        assert "content_gate" in stub.calls

    def test_a_scope_exclusion_answered_goes_through(self):
        answered = frozenset({"scope_excluded_international"})
        result, stub = run(
            EXCLUDING,
            article=article(answered=answered),
            scope=ok("scope", meta("international")),
        )
        assert result.status == "enriched"
        assert "places" in stub.calls

    def test_an_answer_to_a_different_claim_does_not_unlock_this_one(self):
        """One answer, one question. Overruling the scope call says nothing
        about whether the body is news."""
        result, _ = run(
            FULL,
            article=article(answered=frozenset({"scope_excluded_international"})),
            content_gate=ok("content_gate", {"verdict": "not_news", "reason": ""}),
        )
        assert result.status == "not_article"


# ---------------------------------------------------------------------------
# Seam: the answer travels from the row to the gate.
# ---------------------------------------------------------------------------


class TestTheAnswerReachesTheGateFromTheRow:
    def _row(self, metadata):
        return SimpleNamespace(
            id="a1",
            title="T",
            content=STORY,
            metadata=metadata,
            dataset_slug="ds",
            publication_city="Columbia",
        )

    def test_a_decision_the_console_wrote_is_read_off_the_row(self):
        """Through `_rows_to_articles`, as production reads it -- the only
        mapping from a row to what the gate sees."""
        answered = answered_on({}, NOT_NEWS_SKIP_REASON)
        [inp] = _rows_to_articles([self._row(answered)])
        assert NOT_NEWS_SKIP_REASON in inp.answered

    def test_metadata_as_text_is_read_too(self):
        """The column is json; a driver may hand it back as a string."""
        answered = answered_on({}, NOT_NEWS_SKIP_REASON)
        [inp] = _rows_to_articles([self._row(json.dumps(answered))])
        assert NOT_NEWS_SKIP_REASON in inp.answered

    def test_an_extraction_stage_answer_does_not_bind_the_gate(self):
        """Different stage, different question. A reviewer who said the
        extraction was fine did not rule on what the model would find."""
        extraction_answer = contract.record_decision(
            {},
            contract.build_decision(
                claim=NOT_NEWS_SKIP_REASON, stage="extraction", decision="accept"
            ),
        )
        [inp] = _rows_to_articles([self._row(extraction_answer)])
        assert inp.answered == frozenset()

    def test_no_metadata_means_nothing_answered(self):
        [inp] = _rows_to_articles([self._row(None)])
        assert inp.answered == frozenset()

    def test_a_confirmation_does_not_unlock_the_gate(self):
        """`accept` says the gate was right. The record went to its
        exclusion; if it ever came back, the gate is free to find the same
        thing again. Only an overruling answer binds it."""
        confirmed = answered_on({}, NOT_NEWS_SKIP_REASON, decision="accept")
        [inp] = _rows_to_articles([self._row(confirmed)])
        assert inp.answered == frozenset()

    def test_round_trip_a_console_answer_unlocks_the_gate(self):
        """The whole path: console writes the answer onto the row, the
        repository reads it, the gate honours it."""
        answered = answered_on({}, NOT_NEWS_SKIP_REASON)
        [inp] = _rows_to_articles([self._row(answered)])
        result, stub = run(
            FULL,
            article=inp,
            content_gate=ok("content_gate", {"verdict": "not_news", "reason": ""}),
        )
        assert result.status == "enriched"
        assert "places" in stub.calls


# ---------------------------------------------------------------------------
# Seam: the path housekeeping actually runs.
# ---------------------------------------------------------------------------


class TestTheAnswerReachesTheGateOnTheIdsFilePath:
    """`select_by_ids` is what `enrich backfill --ids-file` calls, which is
    what the housekeeping rework step runs -- and the ONLY way a released
    record comes back. Every test above this went through
    `_rows_to_articles`, which the rework path does not use: it builds its
    own `ArticleInput`. It built one with no `answered` at all, and the SQL
    selected the metadata column it then ignored. Green tests, and a record
    held, released by a reviewer, and held again by the next run."""

    def _select(self, metadata):
        session = MagicMock()
        row = SimpleNamespace(
            id="a1",
            title="T",
            content=STORY,
            metadata=metadata,
            status="labeled",
            wire_check_status="complete",
            enrichment_attempts=0,
            dataset_slug="ds",
            publication_city="Columbia",
            publication_state="MO",
            reviewed_kind=None,
        )
        session.execute.return_value.fetchall.return_value = [row]
        report = repository.select_by_ids(session, ["a1"], max_attempts=3)
        # Every predicate in this function rejects into `rejected` rather
        # than raising, so a row that fails one leaves an empty candidate
        # list and the assertions below would fail as an IndexError with
        # nothing to read. Say which predicate instead.
        assert not report.rejected, report.rejected
        return report

    def test_a_released_record_carries_its_answer_into_enrichment(self):
        report = self._select(answered_on({}, NOT_NEWS_SKIP_REASON))
        [candidate] = report.candidates
        assert NOT_NEWS_SKIP_REASON in candidate.answered

    def test_and_the_gate_then_lets_it_through(self):
        """The whole loop closed: reviewer answers, rework selects the
        record by id, the gate honours the answer instead of refusing."""
        report = self._select(answered_on({}, NOT_NEWS_SKIP_REASON))
        result, stub = run(
            FULL,
            article=report.candidates[0],
            content_gate=ok("content_gate", {"verdict": "not_news", "reason": ""}),
        )
        assert result.status == "enriched"
        assert "places" in stub.calls

    def test_an_unanswered_record_on_the_same_path_is_still_refused(self):
        report = self._select(None)
        assert report.candidates[0].answered == frozenset()
        result, _ = run(
            FULL,
            article=report.candidates[0],
            content_gate=ok("content_gate", {"verdict": "not_news", "reason": ""}),
        )
        assert result.status == "not_article"

    def test_every_path_that_builds_an_article_input_passes_answered(self):
        """The defect in one assertion. `answered` defaults to empty, so a
        construction site that forgets it is silently wrong -- no signature
        error, no failing test, just a gate that cannot see the decision."""
        import ast
        import inspect

        source = inspect.getsource(repository)
        built = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "ArticleInput"
        ]
        assert built, "no ArticleInput construction found"
        for node in built:
            assert "answered" in {kw.arg for kw in node.keywords}, (
                f"ArticleInput built at line {node.lineno} of repository.py "
                "without `answered`: the gate there cannot see a reviewer's "
                "decision and will re-raise a refusal that was overruled"
            )
