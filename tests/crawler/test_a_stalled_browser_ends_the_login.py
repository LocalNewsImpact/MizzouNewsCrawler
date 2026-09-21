"""A stalled browser ends the login, and the credentialed worker gets the CPU.

Rotation `authenticated-extraction-7npb2`, 2026-09-21: chromedriver stopped
answering four times in two hours, on yakimaherald, spokesman and ptleader. The
pod's one core was throttled in 18,144 of 26,270 CFS periods (69%).

#650 replaced a dead driver on an ARTICLE load. A LOGIN load swallowed the same
failure and carried on. Spokesman at 17:08 UTC:

    auth0 login: navigation to authorize URL failed:
        HTTPConnectionPool(host='localhost', port=36403): Read timed out.
    (three minutes of field lookups against the stalled driver)
    Login form found by shape (identifier-first: no password field on this screen)
    Authenticated login: password field not found
    Login to spokesman.com did not confirm on attempt 1 of 2

Pinned here:

- every login mechanism loads its page through one helper, which raises on a
  dead driver and logs anything else as before;
- `perform_login` lets that through instead of turning it into "did not confirm";
- the caller replaces the driver and charges the host nothing -- no refusal, no
  `auth_last_failed_at`;
- the credentialed worker runs with 2 cores; the anonymous fleet keeps 1.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.crawler import ContentExtractor
from src.crawler import authenticated_login as al
from src.crawler.driver_health import DriverUnresponsive

urllib3_exceptions = pytest.importorskip("urllib3.exceptions")
selenium_exceptions = pytest.importorskip("selenium.common.exceptions")
yaml = pytest.importorskip("yaml")


def _dead():
    return urllib3_exceptions.ReadTimeoutError(
        None, "http://localhost:36403", "Read timed out. (read timeout=30)"
    )


class TestTheLoginPageLoad:
    def test_a_dead_driver_raises(self):
        driver = MagicMock()
        driver.get.side_effect = _dead()
        with pytest.raises(DriverUnresponsive):
            al._open(driver, "https://login.spokesman.com/authorize", "auth0 login")

    def test_a_slow_page_is_logged_and_the_login_carries_on(self, caplog):
        """Unchanged: an ad-heavy homepage that times out still has a DOM."""
        driver = MagicMock()
        driver.get.side_effect = selenium_exceptions.TimeoutException("slow")
        al._open(driver, "https://www.union-bulletin.com/", "form login")
        assert "form login: navigation to login URL failed" in caplog.text

    @pytest.mark.parametrize(
        "fn",
        [
            "_login_auth0",
            "_login_form",
            "_login_newzware",
            "_login_simplecirc",
            "_login_etype",
        ],
    )
    def test_every_mechanism_loads_through_it(self, fn):
        body = inspect.getsource(getattr(al, fn))
        assert "_open(driver," in body
        assert "driver.get(" not in body

    def test_perform_login_does_not_swallow_it(self):
        with patch.object(al, "_login_auth0", side_effect=DriverUnresponsive("x")):
            with pytest.raises(DriverUnresponsive):
                al.perform_login(
                    MagicMock(),
                    auth_type="auth0",
                    auth_config={},
                    credentials={"username": "u", "password": "p"},
                )

    def test_perform_login_still_swallows_everything_else(self):
        with patch.object(al, "_login_auth0", side_effect=ValueError("boom")):
            assert (
                al.perform_login(
                    MagicMock(),
                    auth_type="auth0",
                    auth_config={},
                    credentials={"username": "u", "password": "p"},
                )
                is False
            )


@pytest.fixture
def login_state():
    saved = (
        ContentExtractor._authenticated_domains,
        ContentExtractor._auth_failed_domains,
        ContentExtractor._auth_attempts,
    )
    ContentExtractor._authenticated_domains = set()
    ContentExtractor._auth_failed_domains = set()
    ContentExtractor._auth_attempts = {}
    yield
    (
        ContentExtractor._authenticated_domains,
        ContentExtractor._auth_failed_domains,
        ContentExtractor._auth_attempts,
    ) = saved


class TestTheCallerReplacesTheDriver:
    def _extractor(self):
        e = ContentExtractor.__new__(ContentExtractor)
        e._get_domain_auth_config = MagicMock(
            return_value={
                "auth_type": "auth0",
                "auth_config": {},
                "auth_secret_name": "publisher-auth-spokesman-com",
            }
        )
        e.close_persistent_driver = MagicMock()
        e._record_login_failure = MagicMock()
        e._record_login_success = MagicMock()
        return e

    def _run(self, e):
        with (
            patch.object(
                al,
                "resolve_auth_credentials",
                return_value={"username": "u", "password": "p"},
            ),
            patch.object(
                al, "perform_login", side_effect=DriverUnresponsive("stalled")
            ),
        ):
            return e._ensure_authenticated(MagicMock(), "www.spokesman.com")

    def test_it_is_not_fetched_and_the_driver_is_replaced(self, login_state):
        e = self._extractor()
        assert self._run(e) is False
        e.close_persistent_driver.assert_called_once_with(unresponsive=True)

    def test_the_host_is_charged_nothing(self, login_state):
        e = self._extractor()
        self._run(e)
        e._record_login_failure.assert_not_called()
        assert "spokesman.com" not in ContentExtractor._auth_failed_domains

    def test_the_handler_comes_before_the_generic_one(self):
        """The generic handler adds the host to `_auth_failed_domains` -- a
        refusal. Order is the whole fix."""
        body = inspect.getsource(ContentExtractor._ensure_authenticated)
        specific = body.index("except DriverUnresponsive")
        generic = body.index("except Exception as e:")
        assert specific < generic
        handler = body[specific:generic]
        assert "close_persistent_driver(unresponsive=True)" in handler
        assert "_auth_failed_domains" not in handler
        assert "_record_login_failure" not in handler


ARGO = Path("k8s/argo")


def _templates(name):
    docs = list(yaml.safe_load_all((ARGO / name).read_text()))
    return {t["name"]: t for d in docs if d for t in d["spec"]["templates"]}


def _args(step):
    return {p["name"]: p.get("value") for p in step["arguments"]["parameters"]}


def _steps(template):
    return {s["name"]: s for group in template.get("steps", []) for s in group}


class TestTheCredentialedWorkerGetsTwoCores:
    @pytest.mark.parametrize(
        "manifest", ["base-pipeline-workflow.yaml", "housekeeping-workflow.yaml"]
    )
    def test_the_patch_sets_cpu_from_the_inputs(self, manifest):
        step = _templates(manifest)["extraction-step"]
        patch_ = json.loads(step["podSpecPatch"])
        (main,) = patch_["containers"]
        assert main["name"] == "main"
        assert main["resources"]["limits"]["cpu"] == "{{inputs.parameters.cpu-limit}}"
        assert (
            main["resources"]["requests"]["cpu"] == "{{inputs.parameters.cpu-request}}"
        )
        assert "memory" not in main["resources"]["limits"]

    def test_the_fleet_default_is_unchanged(self):
        """Anonymous fan-out keeps 1 core: raising the default would multiply."""
        step = _templates("base-pipeline-workflow.yaml")["extraction-step"]
        defaults = {p["name"]: p.get("value") for p in step["inputs"]["parameters"]}
        assert defaults["cpu-limit"] == "1000m"
        assert defaults["cpu-request"] == "250m"

    def test_the_authenticated_rotation_asks_for_two(self):
        tmpl = _templates("authenticated-extraction-workflow.yaml")[
            "extract-credentialed"
        ]
        args = _args(_steps(tmpl)["extract"])
        assert args["cpu-limit"] == "2000m"
        assert args["cpu-request"] == "1000m"

    def test_housekeeping_gives_two_only_to_the_credentialed_pass(self):
        steps = _steps(_templates("housekeeping-workflow.yaml")["housekeeping"])
        assert _args(steps["extract-credentialed"])["cpu-limit"] == "2000m"
        assert _args(steps["extract"])["cpu-limit"] == "1000m"

    def test_the_static_resources_stay_parseable(self):
        """`resources` is typed; a parameter there fails `argo lint` outright."""
        for manifest in ("base-pipeline-workflow.yaml", "housekeeping-workflow.yaml"):
            res = _templates(manifest)["extraction-step"]["container"]["resources"]
            assert "{{" not in json.dumps(res)
