"""The gate is only worth what runs on the path production takes.

Every earlier test called `paywalled_stub(text)` and `no_story(text)` on a
string. None asked which column the string came from, whether the CLI's
`backfill --rework` path reaches the gate at all, or whether a refusal
actually stops the model being called. On 2026-09-13 twelve articles were
enriched in forty minutes and eight held ZERO characters of reporting --
with `content_gate: true` on the dataset and every unit test green.

Two things were true at once that no test could see:

- The repository feeds `a.content`. Every measurement that day was made
  on `COALESCE(a.text, a.content)`, which differs on ~4.5% of articles
  and is LONGER on the ones that got through, so a replay "refused" bodies
  production had let past.
- Nothing asked whether there was an article there at all. Consent text
  and walls each had a check; a subscription form holding every country
  and all fifty states answered neither.

So these tests go in at the seams: the row-to-input mapping, the
orchestrator with a counting adapter, and the CLI's own `_process`.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.enrichment.gate import (
    BOILERPLATE_SKIP_REASON,
    NO_STORY_SKIP_REASON,
    NOT_NEWS_SKIP_REASON,
)
from src.enrichment.orchestrator import PAYWALL_RULE_SKIP_REASON, enrich_article
from src.enrichment.repository import _rows_to_articles
from src.enrichment.types import ArticleInput

from .test_orchestrator import FULL, StubAdapter, ok, run

# ---------------------------------------------------------------------------
# Bodies as production actually stores them.
# ---------------------------------------------------------------------------

#: emissourian, verbatim shape: a subscription checkout form. Every one of
#: these was enriched.
CHECKOUT_FORM = (
    "Country United States of America US Virgin Islands United States Minor "
    "Outlying Islands Canada Mexico, United Mexican States Bahamas, "
    "Commonwealth of the Cuba, Republic of Dominican Republic Haiti, Republic "
    "of Jamaica Afghanistan Albania, People's Socialist Republic of Algeria, "
    "People's Democratic Republic of American Samoa Andorra, Principality of "
    "Angola, Republic of Anguilla Antarctica Zimbabwe What's your delivery "
    "address? Copy billing location Address City State Alabama Alaska Arizona "
    "Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii "
    "Idaho Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland "
    "Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska "
    "Nevada New Hampshire New Jersey New Mexico New York North Carolina North "
    "Dakota Ohio Oklahoma Oregon Pennsylvania Rhode Island South Carolina "
    "South Dakota Tennessee Texas Utah Vermont Virginia Washington West "
    "Virginia Wisconsin Wyoming"
)

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

#: An events listing enriched on 49 characters.
EVENT_LISTING = "Reach Day at His Place Church. Saturday 10 a.m. All welcome."

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
    def test_the_repository_feeds_content_not_text(self):
        """`_rows_to_articles` is the only mapping from a row to what the
        gate sees. If it ever switched columns, every threshold measured
        against production would be measured against the wrong thing --
        which is exactly what happened to the measurements, if not the
        code, on 2026-09-13."""
        row = SimpleNamespace(
            id="a1",
            title="t",
            content=CHECKOUT_FORM,
            text=REAL_STORY,  # the OTHER column: a real story
            dataset_slug="ds",
            publication_city="Columbia",
        )
        [got] = _rows_to_articles([row])
        assert got.content == CHECKOUT_FORM
        assert got.content != REAL_STORY

    def test_a_row_whose_content_is_a_form_is_refused_end_to_end(self):
        """The row as production holds it, through the real mapping, through
        the real orchestrator, to a refusal -- with the model never asked."""
        row = SimpleNamespace(
            id="a1",
            title="t",
            content=CHECKOUT_FORM,
            text=None,
            dataset_slug="ds",
            publication_city="Columbia",
        )
        [inp] = _rows_to_articles([row])
        stub = StubAdapter()
        from src.enrichment import orchestrator

        original = orchestrator.adapter
        orchestrator.adapter = stub
        try:
            outcome = enrich_article(inp, FULL, model="m")
        finally:
            orchestrator.adapter = original
        assert outcome.status == "not_article"
        assert outcome.skip_reason == NO_STORY_SKIP_REASON
        assert stub.calls == [], "a body with no story must never reach a model"
        assert outcome.total_cost_usd == Decimal("0")


# ---------------------------------------------------------------------------
# Seam 2: the orchestrator, with an adapter that counts.
# ---------------------------------------------------------------------------


class TestABodyWithNoStoryNeverReachesAModel:
    def test_the_checkout_form(self):
        result, stub = run(FULL, article=article(CHECKOUT_FORM))
        assert result.status == "not_article"
        assert result.skip_reason == NO_STORY_SKIP_REASON
        assert stub.calls == []

    def test_a_short_all_prose_body_is_not_refused(self):
        """Composition, not length. A one-sentence listing that is entirely
        prose is short, not furniture, and short is deliberately not the
        target: an 87-character brief that is 100% reporting was refused by
        the first cut of this rule and is a real article."""
        result, stub = run(FULL, article=article(EVENT_LISTING))
        assert result.skip_reason != NO_STORY_SKIP_REASON
        assert "content_gate" in stub.calls

    def test_an_empty_body(self):
        result, stub = run(FULL, article=article(""))
        assert result.status == "not_article"
        assert stub.calls == []

    def test_a_long_body_that_is_mostly_furniture_with_a_little_prose(self):
        """The shape the rule is for: a real sentence buried in a form. The
        sentence alone would pass a length test; the body is 95% form."""
        body = "The council met Tuesday and approved the audit. " + CHECKOUT_FORM
        result, stub = run(FULL, article=article(body))
        assert result.skip_reason == NO_STORY_SKIP_REASON
        assert stub.calls == []

    def test_a_real_story_still_goes_through(self):
        """The gate refuses bodies that are mostly not reporting, never
        short reporting. A 123-character sports brief in the clean control
        is real and is 100% story."""
        brief = (
            "JOPLIN, Mo. (KOAM) -- Jason Lazo's 8th-inning grand slam lifts the "
            "Lions over the Panthers. Check out the highlights in the video."
        )
        result, stub = run(FULL, article=article(brief))
        assert result.skip_reason != NO_STORY_SKIP_REASON
        assert "content_gate" in stub.calls

    def test_a_form_scores_nothing_on_consent_terms_so_only_this_catches_it(self):
        """`boilerplate_score` looks for cookie and consent language. A
        checkout form has none, which is how it went to the model."""
        result, _ = run(FULL, article=article(CHECKOUT_FORM))
        assert result.skip_reason == NO_STORY_SKIP_REASON
        assert result.skip_reason != BOILERPLATE_SKIP_REASON

    def test_a_wall_is_checked_before_asking_whether_there_is_a_story(self):
        """THE ORDERING. A teaser plus a stated wall is a walled local
        story -- kept, CIN-coded, not enriched. Asked the other way round
        it reads as "no story" and is filed as not an article, which
        throws away exactly what the paywall rule exists to keep."""
        body = "The council met Tuesday. This item is available in full to subscribers."
        result, _ = run(FULL, article=article(body))
        assert result.status == "enrichment_skipped"
        assert result.skip_reason == PAYWALL_RULE_SKIP_REASON
        assert result.skip_reason != NO_STORY_SKIP_REASON


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

    def test_no_free_refusal_writes_a_null_reason(self):
        for body in (CHECKOUT_FORM, WALLED_WITH_REPEATED_TEASER, ""):
            result, _ = run(FULL, article=article(body))
            assert result.skip_reason, f"unnamed refusal for {body[:40]!r}"


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
        green and the corpus would still fill with enriched forms."""
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
                article(CHECKOUT_FORM),
                article(WALLED_WITH_REPEATED_TEASER),
                article("The council met Tuesday. " + CHECKOUT_FORM),
            ],
            profile=FULL,
            model="m",
            concurrency=1,
        )
        reasons = sorted(o.skip_reason for _, o in persisted)
        assert reasons == sorted(
            [NO_STORY_SKIP_REASON, PAYWALL_RULE_SKIP_REASON, NO_STORY_SKIP_REASON]
        )
        assert summary["counts"] == {"not_article": 2, "enrichment_skipped": 1}
        assert summary["spent"] == "0"
        assert stub.calls == [], "three refusals, zero model calls"
