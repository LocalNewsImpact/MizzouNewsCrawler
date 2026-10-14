"""A login validation runs once, at INFO, against the host it was given.

`k8s/argo/validate-login-workflow.yaml` signs in to a publisher with a real
subscriber account. Three properties of it are not style:

* No retry. Publishers count failed logins -- cascadiadaily.com locks the
  account after a handful -- and a retried validation spends those attempts on
  a credential the first attempt already showed to be wrong.
* INFO logging, not a parameter. At DEBUG selenium logs every browser command,
  and a login's send_keys carries the password into a pod log that ships to
  Cloud Logging (measured 2026-09-20 on the authenticated worker).
* No default host. A validation of the wrong publisher is a login nobody asked
  for on someone's account.

The command line is assembled in bash from optional parameters, so it is run
here for every combination rather than read as a string.
"""

import subprocess
from pathlib import Path

import pytest
import yaml

MANIFEST = (
    Path(__file__).resolve().parent.parent / "k8s/argo/validate-login-workflow.yaml"
)


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(MANIFEST.read_text())


@pytest.fixture(scope="module")
def template(doc):
    (only,) = doc["spec"]["templates"]
    return only


def _parameters(doc):
    return {p["name"]: p for p in doc["spec"]["arguments"]["parameters"]}


def test_nothing_retries_a_login(doc, template):
    assert "retryStrategy" not in doc["spec"]
    assert "retryStrategy" not in template


def test_the_host_has_no_default(doc):
    assert "value" not in _parameters(doc)["host"]


def test_the_log_level_is_not_a_parameter(doc):
    assert not any("log" in name for name in _parameters(doc))


def test_it_logs_at_info(template):
    # The command that runs, not the script text: the script's comment names
    # DEBUG to say why it is not used.
    for record, path in [("false", ""), ("true", "page")]:
        line = _command_line(template, "www.cascadiadaily.com", record, path)
        assert line[:2] == ["--log-level", "INFO"]
        assert "DEBUG" not in line


def test_it_runs_as_the_identity_that_reads_secrets(doc):
    assert doc["spec"]["serviceAccountName"] == "argo-workflow"


def test_it_signs_in_through_the_extraction_egress(template):
    names = {e["name"] for e in template["container"]["env"]}
    assert {"SQUID_PROXY_URL", "SELENIUM_PROXY", "GOOGLE_CLOUD_PROJECT"} <= names


def _command_line(template, host, record, path):
    """Run the container script with the CLI replaced by an echo."""
    script = (
        template["container"]["args"][0]
        .replace("{{inputs.parameters.host}}", host)
        .replace("{{inputs.parameters.record}}", record)
        .replace("{{inputs.parameters.path}}", path)
        .replace("/usr/local/bin/xvfb-wrapper.sh python -m src.cli.cli_modular", "echo")
    )
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    return out.stdout.split()


@pytest.mark.parametrize(
    "record,path,expected_tail",
    [
        ("false", "", []),
        ("true", "", ["--record"]),
        ("false", "page", ["--path", "page"]),
        ("true", "modal", ["--record", "--path", "modal"]),
        # Only the literal "true" records; a typo must not write evidence.
        ("yes", "", []),
    ],
)
def test_the_command_line_for_each_combination(template, record, path, expected_tail):
    assert _command_line(template, "www.cascadiadaily.com", record, path) == [
        "--log-level",
        "INFO",
        "validate-login",
        "--host",
        "www.cascadiadaily.com",
        *expected_tail,
    ]
