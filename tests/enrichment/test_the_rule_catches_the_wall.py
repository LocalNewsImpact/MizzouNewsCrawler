"""A truncated body carrying a subscribe prompt is decided for free.

The LLM content gate spends a call on every article to reach a verdict
that, for the commonest case it sees, a phrase and a length already
settle. Measured against production on 2026-09-06: a paywall phrase
alone also matches real articles that merely mention subscribing, but a
phrase in a body under 900 characters selected paywall stubs at 100%
precision -- 75.7% of known stubs and no real article.

The rule takes only that case. It reaches the same status the paid gate
would, under its OWN skip reason, so a reviewer can tell a rule from a
model and this project can measure what the rule costs in recall.
"""

from __future__ import annotations

from src.enrichment.gate import PAYWALL_STUB_MAX_CHARS, paywalled_stub
from src.enrichment.orchestrator import PAYWALL_RULE_SKIP_REASON
from src.enrichment.types import ArticleInput

from .test_orchestrator import FULL, run

WALL = "To continue reading, please subscribe."


def article(body):
    return ArticleInput("a1", "A headline", body, "ds", "Columbia")


class TestTheRule:
    def test_a_short_walled_body_is_a_stub(self):
        """The phrase is returned, not a bool: which wall fired is the
        evidence the threshold gets retuned on."""
        found = paywalled_stub(f"The council met Tuesday. {WALL}")
        assert isinstance(found, str) and found

    def test_a_long_walled_body_is_left_to_the_gate(self):
        """A full story that also carries a subscribe prompt in its
        furniture is the case the phrase alone gets wrong."""
        body = "The council met Tuesday. " * 60 + WALL
        assert len(body) >= PAYWALL_STUB_MAX_CHARS
        assert paywalled_stub(body) is None

    def test_a_short_body_with_no_wall_is_not_a_stub(self):
        assert paywalled_stub("The council met Tuesday.") is None

    def test_an_empty_body_is_not_a_stub(self):
        assert paywalled_stub("") is None
        assert paywalled_stub(None) is None

    def test_the_threshold_is_exclusive(self):
        """A body exactly at the length is long enough to judge on its
        content, so the rule declines it."""
        body = WALL + "x" * (PAYWALL_STUB_MAX_CHARS - len(WALL))
        assert len(body) == PAYWALL_STUB_MAX_CHARS
        assert paywalled_stub(body) is None
        assert paywalled_stub(body[:-1]) is not None


class TestTheRuleInTheGate:
    def test_a_stub_costs_no_model_call(self):
        result, stub = run(FULL, article=article(f"Council met. {WALL}"))
        assert stub.calls == []
        assert result.total_cost_usd == 0

    def test_a_stub_lands_where_the_paid_gate_would_put_it(self):
        """Same status, so nothing downstream has to learn a new one: the
        stub still exports with its CIN label and byline."""
        result, _ = run(FULL, article=article(f"Council met. {WALL}"))
        assert result.status == "enrichment_skipped"

    def test_the_rule_says_it_was_the_rule(self):
        result, _ = run(FULL, article=article(f"Council met. {WALL}"))
        assert result.skip_reason == PAYWALL_RULE_SKIP_REASON
        assert result.skip_reason != "paywall_stub"

    def test_a_long_walled_article_still_reaches_the_gate(self):
        body = "The council met Tuesday. " * 60 + WALL
        result, stub = run(FULL, article=article(body))
        assert "content_gate" in stub.calls
        assert result.skip_reason != PAYWALL_RULE_SKIP_REASON

    def test_an_ordinary_article_still_reaches_the_gate(self):
        result, stub = run(FULL, article=article("The council met Tuesday."))
        assert "content_gate" in stub.calls

    def test_the_boilerplate_score_still_wins_first(self):
        """A consent wall that also carries a subscribe prompt is not an
        article at all, and must not be filed as a paywalled story."""
        body = "cookies consent privacy policy vendor list opt out " + WALL
        result, _ = run(FULL, article=article(body))
        assert result.status == "not_article"
        assert result.skip_reason is None
