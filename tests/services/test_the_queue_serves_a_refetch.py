"""A rewound link is work, and the queue can hand it out.

`src.pipeline.refetch` rewinds a link to `refetch` when the stored body is a
paywall teaser rather than the story: the article keeps its id, its CIN labels
and its history while its body is replaced. It exists because we hold
subscriptions to the publishers concerned and the text is gettable.

The direct-DB extraction path has honoured it since it was written:

    WHERE cl.status IN ('article', 'refetch')
    AND (cl.status = 'refetch' OR NOT EXISTS (... articles ...))

The queue honoured it in none of its five queries, so a rewound link was
invisible to every worker. Re-extracting through the work queue -- the only
extraction pattern we use -- was impossible for any host, and nothing said so:
the rewind reported success, the link sat at `refetch`, and the queue reported
no work.

`pipeline_rework` is not a way round it. `REWORK_ONLY` is ANDed onto the same
clause, so it narrows what is offered and cannot widen it -- a rework record
still had to be at `article` with no article row. The rework path re-extracts
links that owe a FIRST fetch; it is not a re-fetch path.

Measured against production on 2026-09-20, the authenticated pool for
WSU-Washington-State: the old query offered ptleader 133 links, the new one 141.
The eight are the articles fetched anonymously that morning, whose bodies are
teasers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.services.work_queue import (
    CLAIMABLE_STATUSES,
    NOT_ALREADY_FETCHED,
    REWORK_ONLY,
    WorkQueueCoordinator,
)

DATASET = "c1a654c4-80fa-4b68-bb56-17f08e78065b"


@pytest.fixture
def coordinator():
    with patch("src.services.work_queue.DatabaseManager") as mock_db_class:
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        c = WorkQueueCoordinator()
        c.db = mock_db
        yield c
        c.worker_domains.clear()
        c.domain_cooldowns.clear()
        c.domain_failure_counts.clear()
        c.paused_domains.clear()
        c.pool_requests.clear()


def _domain_sql(coordinator, **kwargs) -> str:
    session = MagicMock()
    session.execute.return_value = iter([])
    coordinator._get_available_domains(session, kwargs.get("dataset"), False, None)
    return str(session.execute.call_args.args[0])


def _item_sql(coordinator) -> str:
    session = MagicMock()
    session.execute.return_value = iter([])
    coordinator._get_available_domains = lambda *a, **k: [
        {
            "source": "ptleader.com",
            "canonical_name": "Port Townsend Leader",
            "article_count": 8,
        }
    ]
    coordinator._request_work_with_session(session, "w1", 3, 3, DATASET)
    return str(session.execute.call_args.args[0])


class TestBothServingQueriesOfferARefetch:
    def test_the_domain_query_does(self, coordinator):
        sql = _domain_sql(coordinator)
        assert "cl.status IN ('article', 'refetch')" in sql

    def test_the_item_query_does(self, coordinator):
        sql = _item_sql(coordinator)
        assert "cl.status IN ('article', 'refetch')" in sql

    def test_neither_still_says_status_equals_article(self, coordinator):
        for sql in (_domain_sql(coordinator), _item_sql(coordinator)):
            assert "cl.status = 'article'" not in sql


class TestAnExistingArticleDisqualifiesOnlyAFirstFetch:
    def test_the_domain_query_exempts_a_rewind(self, coordinator):
        """Replacing that article's body is the whole point of a rewind."""
        sql = _domain_sql(coordinator)
        assert "cl.status = 'refetch' OR NOT EXISTS" in sql

    def test_the_item_query_exempts_a_rewind(self, coordinator):
        sql = _item_sql(coordinator)
        assert "cl.status = 'refetch' OR a.candidate_link_id IS NULL" in sql

    def test_the_exemption_is_not_a_blanket_one(self, coordinator):
        """A link at `article` that already has an article stays excluded --
        that is the invariant `link_status_repair` states, and only `refetch`
        is carved out of it."""
        sql = _domain_sql(coordinator)
        assert "NOT EXISTS" in sql
        assert "a.candidate_link_id = cl.id" in sql

    def test_serving_a_rewind_without_the_exemption_would_look_like_success(self):
        """Why this is not merely a missing row. `ARTICLE_INSERT_SQL` ends
        `ON CONFLICT DO NOTHING`, so a fetch of a link whose article exists pays
        for the request and discards the body."""
        from src.cli.commands import extraction

        assert "ON CONFLICT DO NOTHING" in extraction.ARTICLE_INSERT_SQL.text


class TestTheStatsCountersAgreeWithWhatIsServable:
    def _stats_sql(self, coordinator) -> list[str]:
        session = MagicMock()
        coordinator._get_session = lambda: session
        session.execute.side_effect = [
            MagicMock(scalar=lambda: 1),
            MagicMock(scalar=lambda: 1),
            MagicMock(fetchall=lambda: []),
        ]
        coordinator.get_stats()
        return [str(c.args[0]) for c in session.execute.call_args_list]

    def test_every_counter_counts_a_refetch(self, coordinator):
        """A number that disagrees with what a worker can claim is worse than
        no number: `credentialed_claimable` is read to decide whether work is
        starving."""
        for sql in self._stats_sql(coordinator):
            assert "cl.status IN ('article', 'refetch')" in sql
            assert "cl.status = 'article'" not in sql


class TestReworkCannotSubstituteForThis:
    def test_rework_narrows_rather_than_widens(self):
        """It is ANDed on. A rework record still has to pass the base clause,
        so putting a rewound link in `pipeline_rework` does not make it
        servable."""
        assert REWORK_ONLY.strip().startswith("AND EXISTS")

    def test_the_two_clauses_are_defined_once_each(self):
        """Five queries shared one copy of this filter and all five were wrong
        together. The constants are so that a sixth query cannot disagree."""
        assert "refetch" in CLAIMABLE_STATUSES
        assert "refetch" in NOT_ALREADY_FETCHED


class TestItMatchesTheDirectPath:
    def test_the_same_two_statuses(self):
        """The direct path is the definition; the queue was the one that
        differed."""
        from src.cli.commands import extraction

        assert "cl.status IN ('article', 'refetch')" in extraction.LINK_STATUS_CLAUSE

    def test_the_same_exemption(self):
        from pathlib import Path

        direct = Path("src/cli/commands/extraction.py").read_text()
        assert "cl.status = 'refetch' OR NOT EXISTS" in direct
