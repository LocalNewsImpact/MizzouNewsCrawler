"""A finished article is written when it finishes, not when its turn comes.

`_process` ran the model calls in parallel and then persisted the results
with `pool.map`, which yields in INPUT order. So a fast article sat in
memory behind a slow one ahead of it, and nothing was durable until the
head of the queue cleared.

What that cost, measured rather than supposed: four housekeeping runs on
2026-09-13 made model calls for up to 47 minutes and wrote ZERO enrichment
rows between them. Each was stopped before the ordered yield reached the
front of its queue, and the spend was discarded. A fifth on 2026-09-14 was
13 minutes and 25 completed model calls in, still zero rows.

These tests drive `_process` with articles that finish out of order. On the
ordered version the first assertion fails: the fast article is not written
until the slow one it is queued behind returns.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.cli.commands import enrichment as cli
from src.enrichment.profiles import Profile
from src.enrichment.types import ArticleInput, EnrichmentOutcome

PROFILE = Profile(
    version=3,
    content_gate=False,
    scope=False,
    places=False,
    geocode=False,
    people=False,
    organizations=False,
    metadata_presets=(),
    export_exclude_scopes=(),
)


def article(article_id):
    return ArticleInput(article_id, "T", "body", "ds", "Columbia")


def outcome(article_id, cost="0"):
    return EnrichmentOutcome(
        article_id=article_id,
        status="enriched",
        skip_reason=None,
        steps_applied=[],
        results=[],
        total_cost_usd=Decimal(cost),
    )


@pytest.fixture
def harness(monkeypatch):
    """`_process` with its collaborators replaced: records the order in which
    articles are PERSISTED, which is the thing under test."""
    written = []
    monkeypatch.setattr(
        "src.enrichment.repository.persist_outcome",
        lambda session, art, out, **kw: written.append(art.id),
    )
    monkeypatch.setattr(cli, "_backfield_commit", lambda: "test")
    monkeypatch.setattr(cli, "_max_attempts", lambda: 3)
    monkeypatch.setattr(cli, "_ceiling", lambda: None)
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda s, *a: None
    return written, (lambda: session)


def _run(session_factory, articles, concurrency=4):
    return cli._process(
        session_factory=session_factory,
        articles=articles,
        profile=PROFILE,
        model="m",
        concurrency=concurrency,
    )


class TestAFinishedArticleDoesNotWaitForASlowOneAheadOfIt:
    def test_the_fast_article_is_written_before_the_slow_one_returns(
        self, harness, monkeypatch
    ):
        """THE DEFECT. `slow` is first in the list and blocks for as long as
        it takes `fast` to be written; on `pool.map` that is a deadlock
        broken only by the timeout, because `fast` can never be persisted
        first."""
        written, session_factory = harness
        fast_was_written = threading.Event()

        def enrich(art, profile, model=None, max_attempts=None):
            if art.id == "slow":
                # Returns only once the fast article has been PERSISTED.
                # Ordered persistence cannot get there, so this waits out
                # its timeout and the assertion below fails.
                fast_was_written.wait(timeout=5)
            return outcome(art.id)

        monkeypatch.setattr("src.enrichment.orchestrator.enrich_article", enrich)

        def persist(session, art, out, **kw):
            written.append(art.id)
            if art.id == "fast":
                fast_was_written.set()

        monkeypatch.setattr("src.enrichment.repository.persist_outcome", persist)

        started = time.monotonic()
        summary = _run(session_factory, [article("slow"), article("fast")])
        elapsed = time.monotonic() - started

        assert (
            written[0] == "fast"
        ), "the fast article waited for the slow one ahead of it in the list"
        assert elapsed < 4, "persistence was blocked until the wait timed out"
        assert summary["counts"] == {"enriched": 2}

    def test_every_article_is_still_persisted_exactly_once(self, harness, monkeypatch):
        """Out-of-order persistence must not mean lost or duplicated work."""
        written, session_factory = harness
        monkeypatch.setattr(
            "src.enrichment.orchestrator.enrich_article",
            lambda art, profile, model=None, max_attempts=None: outcome(art.id),
        )
        ids = [f"a{n}" for n in range(25)]
        summary = _run(session_factory, [article(i) for i in ids])
        assert sorted(written) == sorted(ids)
        assert len(written) == len(ids)
        assert summary["counts"] == {"enriched": 25}


class TestTheCeilingStillHalts:
    def test_it_halts_and_keeps_what_it_wrote(self, harness, monkeypatch):
        """The ceiling is checked between articles, and the articles already
        persisted stay persisted -- which is now most of them rather than
        none of them."""
        written, session_factory = harness
        monkeypatch.setattr(cli, "_ceiling", lambda: Decimal("0.03"))
        monkeypatch.setattr(
            "src.enrichment.orchestrator.enrich_article",
            lambda art, profile, model=None, max_attempts=None: outcome(art.id, "0.01"),
        )
        summary = _run(
            session_factory, [article(f"a{n}") for n in range(20)], concurrency=2
        )
        assert summary["halted"] is True
        assert Decimal(summary["spent"]) >= Decimal("0.03")
        # It stopped near the ceiling rather than paying for all twenty.
        assert len(written) < 20
        assert len(written) == sum(summary["counts"].values())

    def test_no_ceiling_means_every_article_runs(self, harness, monkeypatch):
        written, session_factory = harness
        monkeypatch.setattr(
            "src.enrichment.orchestrator.enrich_article",
            lambda art, profile, model=None, max_attempts=None: outcome(art.id, "1.00"),
        )
        summary = _run(session_factory, [article(f"a{n}") for n in range(6)])
        assert summary["halted"] is False
        assert len(written) == 6
        assert Decimal(summary["spent"]) == Decimal("6.00")


class TestAnErrorDoesNotStrandTheRest:
    def test_one_article_raising_does_not_lose_the_others(self, harness, monkeypatch):
        """A raise inside a worker surfaces at `future.result()`. It must not
        take the run down silently with finished work unwritten -- so the
        articles persisted before it stay persisted, and the failure is
        visible."""
        written, session_factory = harness

        def enrich(art, profile, model=None, max_attempts=None):
            if art.id == "boom":
                raise RuntimeError("provider exploded")
            return outcome(art.id)

        monkeypatch.setattr("src.enrichment.orchestrator.enrich_article", enrich)
        with pytest.raises(RuntimeError):
            _run(
                session_factory,
                [article("a"), article("b"), article("boom")],
                concurrency=1,
            )
        # Whatever finished before the raise is on disk, not discarded.
        assert set(written) <= {"a", "b"}
