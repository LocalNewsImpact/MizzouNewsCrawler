"""A work item carries its link status, because the worker writes differently.

`refetch` is a rewind: the article exists and its body is being replaced, so the
body is written with `ARTICLE_REFETCH_SQL`. An ordinary first fetch inserts, and
`ARTICLE_INSERT_SQL` ends `ON CONFLICT DO NOTHING`.

The worker used to build its rows from queue items with the status hardcoded:

    rows = [(item["id"], item["url"], item["source"],
             "article",                     # <- always
             item.get("canonical_name"), item.get("meta")) ...]

While the queue only ever served links at `article` that was harmless. The
moment the queue learned to serve `refetch` (#633), it became a way to spend an
authenticated request on a paywalled publisher and throw the answer away: the
fetch succeeds, the insert conflicts, nothing is written, and the run reports
success. `src/pipeline/refetch.py` predicted exactly this -- "it would look like
it worked" -- about the naive rewind, and serving one through the queue
reproduced it.

129 rewinds were pending when #633 merged, 117 of them from a shared-body audit.
They were cleared rather than left to be fetched and discarded.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from src.services.work_queue import WorkItem, WorkQueueCoordinator

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


class TestTheItemCarriesIt:
    def test_a_work_item_has_a_status(self):
        assert "status" in WorkItem.model_fields

    def test_it_defaults_to_article(self):
        """A worker talking to an older queue behaves as it did, rather than
        crashing on a missing field."""
        item = WorkItem(id="1", url="u", source="s")
        assert item.status == "article"

    def test_a_refetch_round_trips(self):
        assert (
            WorkItem(id="1", url="u", source="s", status="refetch").status == "refetch"
        )


class TestTheQueueSelectsAndSendsIt:
    def test_the_item_query_selects_the_status(self, coordinator):
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
        sql = str(session.execute.call_args.args[0])
        assert "cl.status" in sql.split("FROM")[0], "status must be in the SELECT list"

    def test_the_status_reaches_the_item(self, coordinator):
        session = MagicMock()
        session.execute.return_value = iter(
            [
                (
                    "id1",
                    "https://ptleader.com/a",
                    "ptleader.com",
                    "Port Townsend Leader",
                    "refetch",
                )
            ]
        )
        coordinator._get_available_domains = lambda *a, **k: [
            {
                "source": "ptleader.com",
                "canonical_name": "Port Townsend Leader",
                "article_count": 1,
            }
        ]
        response = coordinator._request_work_with_session(session, "w1", 3, 3, DATASET)
        assert response.items
        assert response.items[0].status == "refetch"

    def test_a_first_fetch_still_says_article(self, coordinator):
        session = MagicMock()
        session.execute.return_value = iter(
            [
                (
                    "id1",
                    "https://ptleader.com/a",
                    "ptleader.com",
                    "Port Townsend Leader",
                    "article",
                )
            ]
        )
        coordinator._get_available_domains = lambda *a, **k: [
            {
                "source": "ptleader.com",
                "canonical_name": "Port Townsend Leader",
                "article_count": 1,
            }
        ]
        response = coordinator._request_work_with_session(session, "w1", 3, 3, DATASET)
        assert response.items[0].status == "article"


class TestTheWorkerUsesIt:
    def test_it_no_longer_hardcodes_article(self):
        from src.cli.commands import extraction

        source = inspect.getsource(extraction)
        start = source.index("# Convert work items to row format")
        block = source[start : start + 900]
        body = "\n".join(
            line for line in block.splitlines() if not line.strip().startswith("#")
        )
        # A line that is ONLY the literal. `item.get("status") or "article",`
        # also ends in `"article",`, so a substring test fails with the fix in
        # place and passes without it -- backwards, which is how this test first
        # failed.
        hardcoded = [ln for ln in body.splitlines() if ln.strip() == '"article",']
        assert not hardcoded, "the status is hardcoded again"
        assert 'item.get("status") or "article"' in body

    def test_the_worker_branches_on_refetch(self):
        """What the status is for: a rewind takes ARTICLE_REFETCH_SQL, and the
        ordinary path would discard the body on conflict."""
        from src.cli.commands import extraction

        source = inspect.getsource(extraction)
        assert "status == REFETCH" in source
        assert "ARTICLE_REFETCH_SQL" in source
        assert "ON CONFLICT DO NOTHING" in extraction.ARTICLE_INSERT_SQL.text
