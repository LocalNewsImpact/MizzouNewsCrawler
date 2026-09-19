"""The gate is only worth what runs on the path production takes.

Every earlier test called `paywalled_stub(text)` on a string. None asked
which column the string came from, whether the CLI's `backfill --rework`
path reaches the gate at all, or whether a refusal actually stops the model
being called. On 2026-09-13 six articles carrying "available in full to
subscribers" were paid for in one run, with `content_gate: true` on the
dataset and every unit test green.

Two things were true at once that no test could see:

- The repository feeds `a.raw`. Every measurement that day was made
  on `COALESCE(a.text, a.raw)`, which differs on ~4.5% of articles.
- A stated wall was subject to a length test that the capture could
  inflate: the teaser repeated, the headline again, "| Log in".

Whether a body is a story at all -- a form, a script dump, a rail -- is the
post-extraction classification stage's question, asked before a CIN label
is applied. It is deliberately not answered here.

So these tests go in at the seams: the row-to-input mapping, the
orchestrator with a counting adapter, and the CLI's own `_process`.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.enrichment.gate import BOILERPLATE_SKIP_REASON, NOT_NEWS_SKIP_REASON
from src.enrichment.orchestrator import PAYWALL_RULE_SKIP_REASON, enrich_article
from src.enrichment.repository import _rows_to_articles
from src.enrichment.types import ArticleInput

from .test_orchestrator import FULL, StubAdapter, ok, run

#: warrencountyrecord, verbatim shape: a decisive wall, with the teaser
#: REPEATED and furniture around it so that a length measurement reads
#: 2,000+ characters of "story". The length rule declined six of these in
#: one run and a model had to be paid to say what the sentence says.
WALLED_WITH_REPEATED_TEASER = (
    "| Log in Warren County Public invited to master plan open house March 25 "
    "Posted 3/23/26 Warren County residents and business owners are invited to "
    "attend a Community Open House for the Warren County Master Plan on "
    "Wednesday, March 25, from 4:30 - 7 p.m. Attention subscribers We have "
    "recently launched a new and improved website. Warren County Public "
    "invited to master plan open house March 25 Posted 3/23/26 Warren County "
    "residents and business owners are invited to attend a Community Open "
    "House for the Warren County Master Plan on Wednesday, March 25, from "
    "4:30 - 7 p.m. This item is available in full to subscribers. Subscribe "
    "now! Log in. Warren County residents and business owners are invited to "
    "attend a Community Open House for the Warren County Master Plan on "
    "Wednesday, March 25, from 4:30 - 7 p.m. Featured Local Savings Featured "
    "Local Savings Copyright 2026 Warren County Record | Copyright/Terms of "
    "Use Powered by Creative Circle Media Solutions X"
)

REAL_STORY = (
    "The council met Tuesday to review the budget. Members voted to fund the "
    "water main replacement on Third Street. The measure passed four to one "
    "after an hour of public comment. Residents of the north side asked about "
    "the schedule for repairs. The city engineer said work would begin in the "
    "spring, and that the contractor had already been selected."
)


def article(body):
    return ArticleInput("a1", "A headline", body, "ds", "Columbia")


# ---------------------------------------------------------------------------
# Seam 1: which column reaches the gate.
# ---------------------------------------------------------------------------


class TestTheGateScoresTheColumnProductionReads:
    def test_the_repository_feeds_raw_not_text(self):
        """`_rows_to_articles` is the only mapping from a row to what the
        gate sees. If it ever switched columns, every threshold measured
        against production would be measured against the wrong thing --
        which is exactly what happened to the measurements, if not the
        code, on 2026-09-13."""
        row = SimpleNamespace(
            id="a1",
            title="t",
            raw=WALLED_WITH_REPEATED_TEASER,
            text=REAL_STORY,  # the OTHER column: a real story
            dataset_slug="ds",
            publication_city="Columbia",
        )
        [got] = _rows_to_articles([row])
        assert got.content == WALLED_WITH_REPEATED_TEASER
        assert got.content != REAL_STORY

    def test_a_row_reaches_the_orchestrator_through_the_real_mapping(self):
        """The row as production holds it, through the real mapping and the
        real orchestrator. A decisive wall in `raw` is refused with the
        model never asked; a wall only in `text` is invisible, because
        `text` is not what the gate reads."""
        from src.enrichment import orchestrator

        for content, text, expect_refused in (
            (WALLED_WITH_REPEATED_TEASER, REAL_STORY, True),
            (REAL_STORY, WALLED_WITH_REPEATED_TEASER, False),
        ):
            row = SimpleNamespace(
                id="a1",
                title="t",
                raw=content,
                text=text,
                dataset_slug="ds",
                publication_city="Columbia",
            )
            [inp] = _rows_to_articles([row])
            stub = StubAdapter()
            original = orchestrator.adapter
            orchestrator.adapter = stub
            try:
                outcome = enrich_article(inp, FULL, model="m")
            finally:
                orchestrator.adapter = original
            if expect_refused:
                assert outcome.skip_reason == PAYWALL_RULE_SKIP_REASON
                assert stub.calls == []
                assert outcome.total_cost_usd == Decimal("0")
            else:
                assert "content_gate" in stub.calls


# ---------------------------------------------------------------------------
# Seam 2: the orchestrator, with an adapter that counts.
# ---------------------------------------------------------------------------


class TestADecisiveWallIsNotSubjectToALengthTest:
    def test_the_repeated_teaser_capture_is_a_stub(self):
        """2,000+ characters by any length measure, and a stub. The body
        SAYS the content is withheld; there is nothing to measure."""
        result, stub = run(FULL, article=article(WALLED_WITH_REPEATED_TEASER))
        assert result.status == "enrichment_skipped"
        assert result.skip_reason == PAYWALL_RULE_SKIP_REASON
        assert stub.calls == [], "a stated wall must never cost a model call"

    def test_the_same_wall_on_a_short_body(self):
        body = "The council met Tuesday. This item is available in full to subscribers."
        result, stub = run(FULL, article=article(body))
        assert result.status == "enrichment_skipped"
        assert result.skip_reason == PAYWALL_RULE_SKIP_REASON
        assert stub.calls == []

    def test_a_long_real_story_that_merely_mentions_subscribing_still_goes_through(
        self,
    ):
        """The length test still guards the WEAK signals. 'Subscribe' in
        the furniture of a complete article is not a wall."""
        body = REAL_STORY * 4 + " Subscribe to our newsletter for more local news."
        result, stub = run(FULL, article=article(body))
        assert result.skip_reason != PAYWALL_RULE_SKIP_REASON
        assert "content_gate" in stub.calls

    def test_a_short_all_prose_body_goes_to_the_model_not_to_a_refusal(self):
        """Whether a short body is a story is not this gate's question. A
        one-sentence brief is passed on, and the post-extraction
        classification stage is where that judgement lives."""
        result, stub = run(
            FULL, article=article("Reach Day at His Place Church. Saturday 10 a.m.")
        )
        assert "content_gate" in stub.calls


class TestEveryGateRefusalIsNamed:
    """A rejection with `skip_reason = NULL` reads as a completed
    enrichment. 179 production rows did, until their entity counts were
    checked."""

    def test_the_models_not_news_verdict_has_a_reason(self):
        result, _ = run(
            FULL,
            article=article(REAL_STORY),
            content_gate=ok("content_gate", {"verdict": "not_news", "reason": ""}),
        )
        assert result.status == "not_article"
        assert result.skip_reason == NOT_NEWS_SKIP_REASON

    def test_the_boilerplate_score_has_a_reason(self):
        body = "cookies consent privacy policy vendor list opt out advertising partners"
        result, _ = run(FULL, article=article(body + " " + REAL_STORY))
        assert result.status == "not_article"
        assert result.skip_reason == BOILERPLATE_SKIP_REASON

    def test_the_wall_refusal_has_a_reason(self):
        result, _ = run(FULL, article=article(WALLED_WITH_REPEATED_TEASER))
        assert result.skip_reason == PAYWALL_RULE_SKIP_REASON


# ---------------------------------------------------------------------------
# Seam 3: the CLI's own loop, which is what `backfill --rework` runs.
# ---------------------------------------------------------------------------


class TestTheCliLoopPersistsWhatTheGateDecided:
    def test_a_refused_article_is_persisted_as_refused_and_costs_nothing(
        self, monkeypatch
    ):
        """`_process` is the production entry: it calls `enrich_article`
        and hands the outcome to `persist_outcome`. If the gate's verdict
        did not survive that hand-off, the unit tests above would all be
        green and the corpus would still fill with paid-for stubs."""
        from src.cli.commands import enrichment as cli
        from src.enrichment import orchestrator

        stub = StubAdapter()
        monkeypatch.setattr(orchestrator, "adapter", stub)
        persisted = []
        monkeypatch.setattr(
            "src.enrichment.repository.persist_outcome",
            lambda session, art, outcome, **kw: persisted.append((art, outcome)),
        )
        monkeypatch.setattr(cli, "_ceiling", lambda: None)
        monkeypatch.setattr(cli, "_max_attempts", lambda: 3)
        monkeypatch.setattr(cli, "_backfield_commit", lambda: "test")

        session = MagicMock()
        session.__enter__ = lambda s: s
        session.__exit__ = lambda s, *a: None

        summary = cli._process(
            session_factory=lambda: session,
            articles=[
                article(WALLED_WITH_REPEATED_TEASER),
                article(
                    "The council met Tuesday. This item is available in full "
                    "to subscribers."
                ),
                article("Login to continue reading. Sign up for complimentary access."),
            ],
            profile=FULL,
            model="m",
            concurrency=1,
        )
        reasons = [o.skip_reason for _, o in persisted]
        assert reasons == [PAYWALL_RULE_SKIP_REASON] * 3
        assert summary["counts"] == {"enrichment_skipped": 3}
        assert summary["spent"] == "0"
        assert stub.calls == [], "three refusals, zero model calls"
