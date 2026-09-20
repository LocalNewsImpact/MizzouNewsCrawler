"""Credentialed hosts get a worker of their own, and the hole that leaves is visible.

Segregating the pools is not one change. `WorkRequest.requires_login` on its
own does nothing: a credentialed domain is still offered to whichever worker
asks first, so an ordinary pipeline worker signs in to a paywalled publisher on
a driver it recycles every three fetches -- unwatched, which is the one thing a
paywalled host's first run must never be.

So every ordinary extraction path has to assert `requires_login=False`. That
closes the leak and opens a different one: once anonymous workers exclude those
domains, nothing else takes them unless an authenticated worker runs, and
"no work for me" is indistinguishable from "no work at all" to a worker. The
run succeeds, the paywalled backlog does not move, and nobody is told.

The parts, and what each is for:

- `src/utils/worker_pool.py` -- ONE setting, `EXTRACTION_WORKER_POOL`, decides
  both which pool a worker asks for and whether its driver holds logins. They
  cannot disagree: asking for credentialed hosts while recycling every three
  fetches is the churn the pool exists to stop.
- the queue also requires `auth_type` and `auth_secret_name` when asked for
  credentialed hosts, because needing a login and being able to perform one are
  different questions. Otherwise the authenticated worker fetches a paywalled
  host anonymously and stores whatever the paywall served -- a failure that
  arrives as content, not as an error.
- `/stats` reports credentialed work: what is owed, what is claimable, why the
  rest is not, and when each pool was last asked for. A host with
  `requires_login` and no credentials is in NEITHER pool; that is a hole, and
  naming it is the difference between a known gap and a silent one.
- `authenticated-extraction` is the worker: one replica, the slow request
  profile, and a documented one-host-at-a-time procedure.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.services.work_queue import WorkQueueCoordinator
from src.utils import worker_pool as wp

ARGO = Path("k8s/argo")


class TestThePoolResolver:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("authenticated", wp.AUTHENTICATED),
            ("anonymous", wp.ANONYMOUS),
            ("mixed", wp.MIXED),
            ("AUTHENTICATED", wp.AUTHENTICATED),
            ("  anonymous  ", wp.ANONYMOUS),
        ],
    )
    def test_it_reads_the_setting(self, value, expected):
        assert wp.worker_pool({wp.ENV_VAR: value}) == expected

    @pytest.mark.parametrize("value", ["", "true", "1", "credentialed", "none"])
    def test_an_unrecognised_value_mixes_rather_than_failing(self, value):
        """A worker is a batch job. Refusing to start would leave the backlog
        untouched and report a failure an operator reads as "extraction is
        broken", where mixing is what every worker did before this existed."""
        assert wp.worker_pool({wp.ENV_VAR: value}) == wp.MIXED

    def test_an_absent_setting_mixes(self):
        assert wp.worker_pool({}) == wp.MIXED

    def test_mixed_is_the_default_so_a_silent_caller_is_safe(self):
        """The dangerous default is `anonymous`: it would exclude credentialed
        domains from every pool the moment this shipped, with no authenticated
        worker running to take them."""
        assert wp.worker_pool({}) != wp.ANONYMOUS


class TestWhatEachPoolAsksFor:
    def test_authenticated_asks_for_credentialed_hosts(self):
        assert wp.requires_login_filter(wp.AUTHENTICATED) is True

    def test_anonymous_asserts_false_rather_than_not_filtering(self):
        """False and None are different claims. None means "any host will do",
        which is what let an ordinary worker pick up a paywalled one."""
        assert wp.requires_login_filter(wp.ANONYMOUS) is False
        assert wp.requires_login_filter(wp.ANONYMOUS) is not None

    def test_mixed_does_not_filter(self):
        assert wp.requires_login_filter(wp.MIXED) is None

    def test_only_the_authenticated_pool_holds_logins(self):
        assert wp.holds_logins(wp.AUTHENTICATED) is True
        assert wp.holds_logins(wp.ANONYMOUS) is False
        assert wp.holds_logins(wp.MIXED) is False

    def test_the_two_answers_agree_for_every_pool(self):
        """A pool that holds logins must be the one that asks for credentialed
        hosts. Reading them from separate settings is how they drift."""
        for pool in wp.POOLS:
            if wp.holds_logins(pool):
                assert wp.requires_login_filter(pool) is True


class TestTheWorkerSendsIt:
    def test_the_request_carries_the_pool_filter(self):
        from src.cli.commands import extraction

        code = inspect.getsource(extraction._get_work_from_queue)
        assert '"requires_login": requires_login' in code

    def test_it_is_omitted_when_the_worker_mixes(self):
        """Sent as null it would be indistinguishable from the filter, and a
        queue that predates the field would reject the payload."""
        from src.cli.commands import extraction

        code = inspect.getsource(extraction._get_work_from_queue)
        assert "if requires_login is None" in code

    def test_the_extract_path_resolves_the_pool(self):
        from src.cli.commands import extraction

        source = Path(inspect.getsourcefile(extraction)).read_text()
        assert "requires_login=requires_login_filter(worker_pool())" in source


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


def _sql_of(session) -> str:
    return str(session.execute.call_args.args[0])


class TestNeedingALoginIsNotBeingAbleToPerformOne:
    def test_the_authenticated_pool_requires_credentials(self, coordinator):
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, None, False, True)

        sql = _sql_of(session)
        assert "s.auth_type IS NOT NULL" in sql
        assert "s.auth_secret_name IS NOT NULL" in sql

    def test_the_anonymous_pool_does_not(self, coordinator):
        """A host needing no login has no credentials to check, and requiring
        them would empty the ordinary pool entirely."""
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session, None, False, False)

        assert "auth_secret_name" not in _sql_of(session)

    def test_mixing_does_not(self, coordinator):
        session = MagicMock()
        session.execute.return_value = iter([])

        coordinator._get_available_domains(session)

        assert "auth_secret_name" not in _sql_of(session)


class TestTheQueueRecordsWhoAsked:
    def _ask(self, coordinator, requires_login):
        session = MagicMock()
        session.execute.return_value = iter([])
        coordinator._get_available_domains = (
            lambda s, d=None, rework=False, requires_login=None: []
        )
        coordinator._request_work_with_session(
            session, "w1", 3, 3, None, False, requires_login
        )

    def test_each_pool_is_recorded_under_its_own_name(self, coordinator):
        self._ask(coordinator, True)
        assert "authenticated" in coordinator.pool_requests
        self._ask(coordinator, False)
        assert "anonymous" in coordinator.pool_requests
        self._ask(coordinator, None)
        assert "mixed" in coordinator.pool_requests

    def test_asking_for_one_pool_does_not_record_another(self, coordinator):
        """The whole value of this is the ABSENCE of an authenticated ask while
        credentialed work is claimable."""
        self._ask(coordinator, False)
        assert "authenticated" not in coordinator.pool_requests

    def test_it_is_recorded_even_when_no_domain_comes_back(self, coordinator):
        """A worker that asked and got nothing is the case worth seeing: it
        distinguishes "nobody came" from "somebody came and found nothing"."""
        self._ask(coordinator, True)
        assert coordinator.pool_requests["authenticated"] > 0


class TestStatsNamesTheStarvation:
    def _stats(self, coordinator, rows):
        session = MagicMock()
        coordinator._get_session = lambda: session
        # available count, domain count, then the credentialed rows
        session.execute.side_effect = [
            MagicMock(scalar=lambda: 10),
            MagicMock(scalar=lambda: 2),
            MagicMock(fetchall=lambda: rows),
        ]
        return coordinator.get_stats()

    def test_claimable_work_is_counted_separately(self, coordinator):
        stats = self._stats(
            coordinator,
            [("ptleader.com", "active", True, 142)],
        )
        assert stats.credentialed_available == 142
        assert stats.credentialed_claimable == 142
        assert stats.credentialed_unclaimable == {}

    def test_a_paused_source_is_named_with_its_reason(self, coordinator):
        stats = self._stats(
            coordinator,
            [("tdn.com", "paused", True, 108)],
        )
        assert stats.credentialed_available == 108
        assert stats.credentialed_claimable == 0
        assert "paused" in stats.credentialed_unclaimable["tdn.com"]
        assert "108" in stats.credentialed_unclaimable["tdn.com"]

    def test_a_host_with_no_credentials_is_named_as_being_in_neither_pool(
        self, coordinator
    ):
        """The anonymous worker excludes it on `requires_login = false` and the
        authenticated worker on the credentials check. Nothing fetches it."""
        stats = self._stats(
            coordinator,
            [("chinookobserver.com", "active", False, 12)],
        )
        assert stats.credentialed_claimable == 0
        reason = stats.credentialed_unclaimable["chinookobserver.com"]
        assert "neither pool" in reason

    def test_owed_is_the_total_whatever_the_reason(self, coordinator):
        stats = self._stats(
            coordinator,
            [
                ("ptleader.com", "active", True, 142),
                ("tdn.com", "paused", True, 108),
                ("nocreds.example", "active", False, 5),
            ],
        )
        assert stats.credentialed_available == 255
        assert stats.credentialed_claimable == 142
        assert len(stats.credentialed_unclaimable) == 2

    def test_no_credentialed_work_reports_zero_not_absent(self, coordinator):
        stats = self._stats(coordinator, [])
        assert stats.credentialed_available == 0
        assert stats.credentialed_claimable == 0

    def test_the_pool_ages_are_reported(self, coordinator):
        coordinator.pool_requests["anonymous"] = 1.0
        stats = self._stats(coordinator, [])
        assert "anonymous" in stats.pool_last_request_age
        assert stats.pool_last_request_age["anonymous"] > 0

    def test_claimable_work_with_no_authenticated_ask_is_logged(
        self, coordinator, caplog
    ):
        """The starvation case, said out loud. A count that never moves is not
        a signal anyone reads."""
        with caplog.at_level("WARNING"):
            self._stats(coordinator, [("ptleader.com", "active", True, 142)])
        assert "authenticated pool" in caplog.text

    def test_it_is_silent_once_a_worker_has_asked(self, coordinator, caplog):
        coordinator.pool_requests["authenticated"] = 1.0
        with caplog.at_level("WARNING"):
            self._stats(coordinator, [("ptleader.com", "active", True, 142)])
        assert "authenticated pool" not in caplog.text


def _template(path: str, name: str) -> dict:
    doc = yaml.safe_load((ARGO / path).read_text())
    for tpl in doc["spec"]["templates"]:
        if tpl["name"] == name:
            return tpl
    raise AssertionError(f"{name} not found in {path}")


def _params(node) -> dict:
    return {
        p["name"]: p.get("value")
        for p in node.get("arguments", {}).get("parameters", [])
    }


class TestTheExtractionStepTakesAPool:
    def test_it_is_an_input_with_a_safe_default(self):
        step = _template("base-pipeline-workflow.yaml", "extraction-step")
        pool = [p for p in step["inputs"]["parameters"] if p["name"] == "worker-pool"]
        assert pool, "extraction-step must take worker-pool"
        assert pool[0]["value"] == "mixed"

    def test_the_setting_reaches_the_container(self):
        step = _template("base-pipeline-workflow.yaml", "extraction-step")
        env = {e["name"]: e.get("value") for e in step["container"]["env"]}
        assert env["EXTRACTION_WORKER_POOL"] == "{{inputs.parameters.worker-pool}}"

    def test_the_authenticated_reuse_limit_is_higher_than_the_ordinary_one(self):
        step = _template("base-pipeline-workflow.yaml", "extraction-step")
        env = {e["name"]: e.get("value") for e in step["container"]["env"]}
        assert int(env["SELENIUM_DRIVER_REUSE_LIMIT_AUTHENTICATED"]) > int(
            env["SELENIUM_DRIVER_REUSE_LIMIT"]
        )


class TestEveryOrdinaryPathAssertsAnonymous:
    def test_the_pipeline_dag_says_so(self):
        """Without this the whole segregation is decorative: a credentialed
        domain goes to whichever worker asks first."""
        dag = _template("base-pipeline-workflow.yaml", "pipeline")
        tasks = {t["name"]: t for t in dag["dag"]["tasks"]}
        assert _params(tasks["extract-content"])["worker-pool"] == "anonymous"

    def test_dataset_extraction_says_so(self):
        doc = yaml.safe_load((ARGO / "dataset-extraction-workflow.yaml").read_text())
        top = {
            p["name"]: p.get("value") for p in doc["spec"]["arguments"]["parameters"]
        }
        assert top["worker-pool"] == "anonymous"

    def test_dataset_extraction_threads_it_to_the_step(self):
        tpl = _template("dataset-extraction-workflow.yaml", "extract-dataset")
        step = tpl["steps"][0][0]
        assert _params(step)["worker-pool"] == "{{inputs.parameters.worker-pool}}"


class TestTheAuthenticatedWorker:
    PATH = "authenticated-extraction-workflow.yaml"

    def test_the_template_exists_and_asks_for_the_authenticated_pool(self):
        tpl = _template(self.PATH, "extract-credentialed")
        step = tpl["steps"][0][0]
        assert _params(step)["worker-pool"] == "authenticated"

    def test_it_reuses_the_tested_extraction_step(self):
        """Copying the step would fork 40-odd env entries, the retry strategy
        and USE_WORK_QUEUE away from the one definition that is exercised."""
        tpl = _template(self.PATH, "extract-credentialed")
        ref = tpl["steps"][0][0]["templateRef"]
        assert ref == {
            "name": "news-pipeline-template",
            "template": "extraction-step",
        }

    def test_there_is_exactly_one_worker(self):
        """Two workers on one host mean two sessions for one subscriber
        account, and the queue rations by domain anyway."""
        tpl = _template(self.PATH, "extract-credentialed")
        step = tpl["steps"][0][0]
        assert "withSequence" not in step
        assert "withParam" not in step
        assert len(tpl["steps"]) == 1
        assert len(tpl["steps"][0]) == 1

    def test_the_dataset_has_no_default(self):
        """An unscoped run draws another corpus's backlog and bills the compute
        to the wrong dataset, or to none."""
        doc = yaml.safe_load((ARGO / self.PATH).read_text())
        dataset = [
            p for p in doc["spec"]["arguments"]["parameters"] if p["name"] == "dataset"
        ][0]
        assert "value" not in dataset

    def test_it_uses_the_slow_request_profile(self):
        """A subscriber session identifies us on every request, so the usual
        argument that rotation hides the traffic does not apply."""
        doc = yaml.safe_load((ARGO / self.PATH).read_text())
        top = {
            p["name"]: p.get("value") for p in doc["spec"]["arguments"]["parameters"]
        }
        open_host = yaml.safe_load(
            (ARGO / "dataset-extraction-workflow.yaml").read_text()
        )
        open_top = {
            p["name"]: p.get("value")
            for p in open_host["spec"]["arguments"]["parameters"]
        }
        for key in ("inter-request-min", "inter-request-max", "batch-sleep"):
            assert float(top[key]) > float(open_top[key]), key

    def test_it_carries_workload_identity(self):
        """A `--from workflowtemplate` submit otherwise defaults to the
        `default` service account and dies on cloudsql.instances.get."""
        doc = yaml.safe_load((ARGO / self.PATH).read_text())
        assert doc["spec"]["serviceAccountName"] == "argo-workflow"

    def test_deploying_applies_it(self):
        """A template that lives only in the repository is a worker that cannot
        run -- and it is now the ONLY thing that fetches credentialed hosts."""
        script = Path("scripts/apply-manifests.sh").read_text()
        assert f"apply_file k8s/argo/{self.PATH}" in script
