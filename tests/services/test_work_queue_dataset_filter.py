"""The work queue must honour a dataset scope, or `--dataset` is a lie.

`extract --dataset X` applies `AND cl.dataset_id = :dataset` on the direct-DB
path, but the work-queue path sent only worker_id/batch_size/max_articles and
the queue's own queries were `WHERE cl.status = 'article'` across every
dataset. So a dataset-scoped extraction run through the standard pipeline
(USE_WORK_QUEUE=true in the Argo template) silently processed other datasets'
backlogs. Found 2026-08-12 while extracting VTCNI: the run would have pulled
Mizzou's ~3,098 article-status links alongside it.

Both queries need the filter, not just one. Domains are assigned from
_get_available_domains, so filtering there stops out-of-dataset domains being
offered; but a single domain can carry links from more than one dataset, so
the item-selection query has to filter too.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.services.work_queue import WorkQueueCoordinator, WorkRequest

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


def _params_of(mock_session) -> list[dict]:
    """Bind parameters from every execute() call, in order."""
    out = []
    for call in mock_session.execute.call_args_list:
        out.append(call.args[1] if len(call.args) > 1 else (call.kwargs or {}))
    return out


class TestAvailableDomainsQuery:
    def test_dataset_is_bound_when_given(self, coordinator):
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, DATASET)

        assert _params_of(session)[0]["dataset"] == DATASET

    def test_no_dataset_means_no_filter_at_all(self, coordinator):
        """No dataset still means draw from all of them, but the clause
        is now absent rather than passed as NULL.

        `AND (:dataset IS NULL OR ...)` is what Postgres could not plan,
        so the parameter is mentioned only when there is a value for it.
        """
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session)

        assert _params_of(session)[0] == {}
        assert "dataset" not in str(session.execute.call_args.args[0])

    def test_the_sql_actually_filters_on_dataset_id(self, coordinator):
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, DATASET)

        sql = str(session.execute.call_args.args[0])
        # The filter is present when a dataset is given, and the
        # parameter appears exactly once.
        #
        # It read `AND (:dataset IS NULL OR cl.dataset_id = :dataset)`
        # until 2026-09-07, which Postgres could not plan at all --
        # 42P18 -- so /work/request answered 500 to every worker from
        # the day #455 shipped it. This test passed throughout, because
        # the session below is a MagicMock: it records the SQL and never
        # sends it anywhere.
        assert "cl.dataset_id = :dataset" in sql
        assert sql.count(":dataset") == 1, "repeating it breaks SQLite binding"


class TestItemSelectionQuery:
    def test_dataset_reaches_the_item_query_too(self, coordinator):
        """A domain can hold links from several datasets, so filtering the
        domain list alone would still hand back out-of-dataset links."""
        session = MagicMock()
        coordinator._get_available_domains = lambda s, d=None: [
            {"source": "example.com", "canonical_name": "Example", "article_count": 5}
        ]
        session.execute.return_value = iter([])

        coordinator._request_work_with_session(
            session,
            "worker-1",
            batch_size=3,
            max_articles_per_domain=3,
            dataset=DATASET,
        )

        params = _params_of(session)
        assert params, "expected the item-selection query to run"
        assert params[-1]["dataset"] == DATASET

    def test_item_sql_filters_on_dataset_id(self, coordinator):
        session = MagicMock()
        coordinator._get_available_domains = lambda s, d=None: [
            {"source": "example.com", "canonical_name": "Example", "article_count": 5}
        ]
        session.execute.return_value = iter([])

        coordinator._request_work_with_session(
            session,
            "worker-1",
            batch_size=3,
            max_articles_per_domain=3,
            dataset=DATASET,
        )

        assert "cl.dataset_id = :dataset" in str(session.execute.call_args.args[0])


class TestScopePropagation:
    def test_request_work_passes_the_dataset_through(self, coordinator):
        seen = {}

        def capture(session, worker_id, batch_size, max_per_domain, dataset=None):
            seen["dataset"] = dataset
            return "sentinel"

        coordinator._request_work_with_session = capture
        coordinator._test_session = MagicMock()

        coordinator.request_work("worker-1", 3, 3, DATASET)

        assert seen["dataset"] == DATASET

    def test_dataset_defaults_to_none(self, coordinator):
        seen = {}

        def capture(session, worker_id, batch_size, max_per_domain, dataset=None):
            seen["dataset"] = dataset
            return "sentinel"

        coordinator._request_work_with_session = capture
        coordinator._test_session = MagicMock()

        coordinator.request_work("worker-1", 3, 3)

        assert seen["dataset"] is None


class TestRequestModel:
    def test_dataset_is_optional(self):
        assert WorkRequest(worker_id="w1").dataset is None

    def test_dataset_round_trips(self):
        assert WorkRequest(worker_id="w1", dataset=DATASET).dataset == DATASET
