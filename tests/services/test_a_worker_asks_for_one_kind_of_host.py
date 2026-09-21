"""A worker can ask the queue for credentialed hosts, or for anonymous ones.

The queue hands a worker one domain and at most three articles, then rotates.
One Selenium driver serves all of them, and it is recycled every
`SELENIUM_DRIVER_REUSE_LIMIT` fetches -- roughly three visits -- which clears
`ContentExtractor._authenticated_domains`. So a worker fetching both kinds of
host signs in to each credentialed publisher again on its next turn. Across the
1,038 WSU links behind seven paywalled publishers that is a great many logins
submitted to publishers who are watching, and `cascadiadaily.com` counts them.

Raising the reuse limit whenever the driver holds a session was the first fix
and it was wrong: `_authenticated_domains` accumulates for the life of the
process, so the first login also stops rotating the anonymous domains in the
same batch, which is the one thing the limit exists to do.

Segregating the work is the fix that does not trade that away. This is the
queue half: a worker says which pool it draws from. `None` mixes, which is what
every caller got before and still gets.

`docs/AN_AUTHENTICATED_WORKER_IS_PROVISIONED.md` records what is still open --
chiefly that an anonymous worker must ask for `requires_login=False`
explicitly, or a credentialed domain is still offered to whoever asks first.
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


def _sql_and_params(session) -> tuple[str, dict]:
    call = session.execute.call_args
    params = call.args[1] if len(call.args) > 1 else (call.kwargs or {})
    return str(call.args[0]), params


class TestTheDomainQueryFiltersOnIt:
    def test_asking_for_credentialed_hosts_binds_true(self, coordinator):
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, None, False, True)

        sql, params = _sql_and_params(session)
        assert "s.requires_login = :requires_login" in sql
        assert params["requires_login"] is True

    def test_asking_for_anonymous_hosts_binds_false(self, coordinator):
        """False is a filter, not an absent one -- the distinction the
        `if requires_login is not None` guard exists for."""
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, None, False, False)

        sql, params = _sql_and_params(session)
        assert "s.requires_login = :requires_login" in sql
        assert params["requires_login"] is False

    def test_omitting_it_leaves_the_clause_out_entirely(self, coordinator):
        """Mixing is the historical behaviour and every current caller's."""
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session)

        sql, params = _sql_and_params(session)
        assert "requires_login" not in sql
        assert "requires_login" not in params

    def test_the_parameter_appears_once(self, coordinator):
        """A repeated named parameter no longer matches its bindings on
        SQLite, where each occurrence becomes its own placeholder. This is
        why the clause is appended rather than written as
        `(:requires_login IS NULL OR ...)`, which Postgres could not plan."""
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, None, False, True)

        sql, _ = _sql_and_params(session)
        assert sql.count(":requires_login") == 1

    def test_it_composes_with_the_dataset_scope(self, coordinator):
        """The paywalled runs are one dataset AND one kind of host."""
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, DATASET, False, True)

        sql, params = _sql_and_params(session)
        assert "cl.dataset_id = :dataset" in sql
        assert "s.requires_login = :requires_login" in sql
        assert params["dataset"] == DATASET
        assert params["requires_login"] is True


class TestTheFlagIsNeverNullInTheColumn:
    def test_sources_requires_login_is_not_nullable(self):
        """`= false` would silently drop every row with a NULL flag, so an
        anonymous worker would see nothing on a schema that allowed NULL."""
        from src.models import Source

        col = Source.__table__.c.requires_login
        assert col.nullable is False
        assert col.server_default is not None


class TestItReachesTheQueryFromTheRequest:
    def _capture(self, seen):
        def capture(
            session,
            worker_id,
            batch_size,
            max_per_domain,
            dataset=None,
            rework=False,
            requires_login=None,
        ):
            seen["requires_login"] = requires_login
            return "sentinel"

        return capture

    def test_request_work_passes_it_through(self, coordinator):
        seen: dict = {}
        coordinator._request_work_with_session = self._capture(seen)
        coordinator._test_session = MagicMock()

        coordinator.request_work("worker-1", 3, 3, DATASET, False, True)

        assert seen["requires_login"] is True

    def test_it_defaults_to_mixing(self, coordinator):
        seen: dict = {}
        coordinator._request_work_with_session = self._capture(seen)
        coordinator._test_session = MagicMock()

        coordinator.request_work("worker-1", 3, 3)

        assert seen["requires_login"] is None

    def test_the_session_method_hands_it_to_the_domain_query(self, coordinator):
        """The whole point is that it reaches the SELECT; passing it into
        `_request_work_with_session` and dropping it there would look
        identical from the API."""
        seen: dict = {}
        session = MagicMock()
        session.execute.return_value = iter([])

        def capture(s, d=None, rework=False, requires_login=None):
            seen["requires_login"] = requires_login
            return []

        coordinator._get_available_domains = capture
        coordinator._request_work_with_session(
            session,
            "worker-1",
            batch_size=3,
            max_articles_per_domain=3,
            dataset=DATASET,
            requires_login=False,
        )

        assert seen["requires_login"] is False


class TestTheRequestModel:
    def test_it_is_optional_and_mixes_by_default(self):
        assert WorkRequest(worker_id="w1").requires_login is None

    def test_both_values_round_trip(self):
        assert WorkRequest(worker_id="w1", requires_login=True).requires_login is True
        assert WorkRequest(worker_id="w1", requires_login=False).requires_login is False

    def test_the_endpoint_forwards_it(self):
        """A field on the model that the endpoint does not pass on is a flag
        the caller can set and nothing reads."""
        import inspect

        from src.services import work_queue

        code = inspect.getsource(work_queue.request_work)
        assert "request.requires_login" in code
