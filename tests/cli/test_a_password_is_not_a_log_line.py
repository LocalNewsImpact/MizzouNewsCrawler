"""A subscriber password must never be a log line, at any level.

`selenium.webdriver.remote.remote_connection` logs every command sent to the
browser, and `send_keys` carries its text as the command payload. So a login at
DEBUG writes the password out as cleartext. From the first authenticated WSU
extraction run, 2026-09-20:

    POST .../element/.../value {'text': 'Newspaper1',
                               'value': ['N','e','w','s','p','a','p','e','r','1']}

The run's workflow template had asked for DEBUG on the reasoning that a watched
login needs the login step's own logging to say whether the session took. It
does not: the crawler says so itself at INFO.

    🔐 tdn.com - subscriber login: authenticated browser only
    Authenticated session established for tdn.com

Pod logs ship to Cloud Logging, so the exposure is not confined to the pod, and
these accounts are shared across a publisher group's titles.

`src/utils/logging_config.py` already quieted `selenium` -- but the CLI calls
`src/cli/context.py::setup_logging`, which set a level and no per-library
levels at all, so the protection that existed never applied to an extraction
run. Two logging setups, and the defended one was not the one in the path.
"""

from __future__ import annotations

import logging

import pytest
import yaml

from src.cli import context


@pytest.fixture(autouse=True)
def _restore_levels():
    """These are process-wide logger objects; a test must not leak into the next."""
    names = ("", "src.crawler", *context._NEVER_BELOW_INFO)
    before = {n: logging.getLogger(n).level for n in names}
    root = logging.getLogger()
    handlers = list(root.handlers)
    yield
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)
    root.handlers = handlers


def _setup(tmp_path, level):
    context.setup_logging(level, log_file=str(tmp_path / "crawler.log"))


class TestTheWireLoggersAreHeldAtInfo:
    @pytest.mark.parametrize("name", context._NEVER_BELOW_INFO)
    def test_debug_does_not_reach_them(self, tmp_path, name):
        _setup(tmp_path, "DEBUG")
        # The logger's own level: NOTSET would pass an effective-level check
        # while the root was quiet and then inherit DEBUG the moment it was not.
        assert logging.getLogger(name).level >= logging.INFO

    def test_the_selenium_command_logger_is_one_of_them(self):
        """Named explicitly: this is the logger that prints `send_keys` text."""
        assert (
            "selenium.webdriver.remote.remote_connection" in context._NEVER_BELOW_INFO
        )

    def test_the_rest_of_the_application_still_gets_debug(self, tmp_path):
        """Containment, not a blanket downgrade -- DEBUG is asked for because
        something else needs it.

        Asserted by setting a logger and checking the guard leaves it, rather
        than by reading a level the guard never touched. Two things make the
        weaker form unreliable: `basicConfig` is a no-op once handlers exist and
        pytest installs its own, so the root level says nothing about a real
        run; and another test in the suite sets `src.crawler` to DEBUG, so
        asserting it is NOTSET passes alone and fails in the suite. It did.
        """
        logging.getLogger("src.crawler").setLevel(logging.DEBUG)
        _setup(tmp_path, "DEBUG")
        assert logging.getLogger("src.crawler").level == logging.DEBUG
        assert "src.crawler" not in context._NEVER_BELOW_INFO

    def test_an_ordinary_run_is_unchanged(self, tmp_path):
        _setup(tmp_path, "INFO")
        for name in context._NEVER_BELOW_INFO:
            assert logging.getLogger(name).level >= logging.INFO

    def test_a_level_below_info_is_raised_not_lowered(self, tmp_path):
        """A logger already set stricter than INFO keeps its own setting: the
        guard is a floor, not an assignment."""
        logging.getLogger(context._NEVER_BELOW_INFO[0]).setLevel(logging.ERROR)
        _setup(tmp_path, "DEBUG")
        assert logging.getLogger(context._NEVER_BELOW_INFO[0]).level == logging.ERROR

    def test_a_quiet_root_does_not_make_the_child_look_safe(self, tmp_path):
        """The defect the first version of this guard had.

        It compared the EFFECTIVE level, which while the root sits at WARNING
        reads as WARNING for a NOTSET child -- so the guard set nothing, and the
        child inherited DEBUG as soon as anything raised the root. The leak,
        one step later.
        """
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger(context._NEVER_BELOW_INFO[0]).setLevel(logging.NOTSET)
        _setup(tmp_path, "DEBUG")
        logging.getLogger().setLevel(logging.DEBUG)
        assert (
            logging.getLogger(context._NEVER_BELOW_INFO[0]).getEffectiveLevel()
            >= logging.INFO
        )


class TestTheActualPayloadIsNotEmitted:
    def test_a_send_keys_style_record_is_dropped_at_debug(self, tmp_path, caplog):
        """The concrete thing: a record shaped like the one that leaked.

        Asserted through the logger the library uses, not through selenium --
        the driver is not available in this suite and the level is what decides.
        """
        _setup(tmp_path, "DEBUG")
        wire = logging.getLogger("selenium.webdriver.remote.remote_connection")
        with caplog.at_level(logging.DEBUG):
            wire.debug("POST .../value {'text': 'Newspaper1'}")
        assert "Newspaper1" not in caplog.text

    def test_a_warning_from_the_same_logger_still_reaches_the_log(
        self, tmp_path, caplog
    ):
        """Silencing it entirely would hide a driver failure worth reading."""
        _setup(tmp_path, "DEBUG")
        wire = logging.getLogger("selenium.webdriver.remote.remote_connection")
        with caplog.at_level(logging.DEBUG):
            wire.warning("session deleted")
        assert "session deleted" in caplog.text


class TestTheWorkflowDoesNotAskForDebug:
    def test_the_authenticated_template_runs_at_info(self):
        """Second line of defence. The code guard is the first, because a
        template is one of several ways a run picks a level."""
        doc = yaml.safe_load(
            open("k8s/argo/authenticated-extraction-workflow.yaml").read()
        )
        params = {
            p["name"]: p.get("value") for p in doc["spec"]["arguments"]["parameters"]
        }
        assert params["log-level"] == "INFO"

    def test_no_argo_template_defaults_to_debug(self):
        """A credentialed host can be extracted by any of these."""
        from pathlib import Path

        for path in Path("k8s/argo").glob("*workflow*.yaml"):
            doc = yaml.safe_load(path.read_text())
            if not isinstance(doc, dict):
                continue
            for param in (doc.get("spec", {}).get("arguments", {}) or {}).get(
                "parameters", []
            ) or []:
                if param.get("name") == "log-level":
                    assert param.get("value") != "DEBUG", path.name
