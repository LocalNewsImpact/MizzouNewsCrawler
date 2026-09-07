"""One step failing threw away every step before it.

191 articles were enriched on 2026-09-07 and 87 of them -- 46% -- wrote
nothing. The sampled cause was a single step, `temporal_orientation`,
returning a confidence outside 0.0-1.0, which the response validator
refuses. content_gate, scope, subject, topic and format had all passed on
that article, and all five were discarded: `transient_failure()` rewinds
the article whole, so the next attempt pays for them again. About $0.46
of the $1.38 spent bought results that were dropped.

The rate is per-article and the defect is per-call. An article needs nine
consecutive validations, so a modest per-call failure rate compounds into
a per-article one. Retrying the step is the cheapest place to break the
chain: the model is sampling, and a second draw is usually valid.

Nothing recorded any of this. The outcome carries the error and
`persist_outcome` writes only the attempt counter for a transient
failure, so the cause was found by re-running articles through the
orchestrator by hand.
"""

import logging
from decimal import Decimal

from src.enrichment import adapter


def _node(results):
    """A node that returns, or raises, whatever the list says -- in order."""
    calls = {"n": 0}

    def fn(params, inputs):
        outcome = results[calls["n"]]
        calls["n"] += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fn.calls = calls
    return fn


def test_a_step_that_fails_once_is_asked_again(monkeypatch):
    node = _node([ValueError("confidence must be between 0.0 and 1."), {"ok": 1}])
    monkeypatch.setattr(adapter, "_load", lambda name: node)

    result = adapter._run_node("temporal_orientation", "article_metadata", {}, {}, "m")

    assert result.ok
    assert result.payload == {"ok": 1}
    assert node.calls["n"] == 2, "the second draw is the point"


def test_a_step_that_keeps_failing_gives_up_and_says_why(monkeypatch):
    boom = ValueError("confidence must be between 0.0 and 1.")
    node = _node([boom, boom])
    monkeypatch.setattr(adapter, "_load", lambda name: node)

    result = adapter._run_node("temporal_orientation", "article_metadata", {}, {}, "m")

    assert not result.ok
    assert result.payload is None
    assert "confidence must be between" in result.error
    assert result.cost_usd == Decimal("0")
    assert node.calls["n"] == adapter.STEP_ATTEMPTS


def test_a_failing_step_is_logged(monkeypatch, caplog):
    """The 87 recorded no reason anywhere. Finding this one needed
    articles re-run through the orchestrator by hand."""
    node = _node([ValueError("confidence must be between 0.0 and 1."), {"ok": 1}])
    monkeypatch.setattr(adapter, "_load", lambda name: node)

    with caplog.at_level(logging.WARNING):
        adapter._run_node("temporal_orientation", "article_metadata", {}, {}, "m")

    assert any(
        "temporal_orientation" in r.getMessage() and "confidence" in r.getMessage()
        for r in caplog.records
    ), "a step that failed has to say so without a person re-running it"


def test_a_step_that_works_first_time_is_asked_once(monkeypatch):
    """The retry must not double the bill for the 102 that were fine."""
    node = _node([{"ok": 1}])
    monkeypatch.setattr(adapter, "_load", lambda name: node)

    result = adapter._run_node("scope", "article_metadata", {}, {}, "m")

    assert result.ok
    assert node.calls["n"] == 1
