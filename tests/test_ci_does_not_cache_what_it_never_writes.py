"""A pip cache is for a job that pip-installs. None of these do.

Every stage of this repository's CI runs inside the image `make
ci-image` pulls, so nothing writes ~/.cache/pip on the runner.
setup-python still ran its post-step, and on a cache MISS that step
fails the job -- after lint or the tests have reported success:

    Cache folder path is retrieved for pip but doesn't exist on disk

On a HIT it was worse than useless. The restore matched by prefix, the
key did not, so the job SAVED the 2.9 GB it had just restored back under
its own key, having installed nothing. Four Dependabot pull requests
doing that is 11.5 GB against a 10 GB budget: the entry every run
restores from was evicted, and the next jobs -- #487, #506, #508 --
missed entirely and went red on work that had passed.

These read the workflow files, because the runner is where it was
already too late.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"
INSTALLS_ON_THE_RUNNER = ("pip install", "pip3 install", "python -m pip install")


def _workflows():
    return sorted(WORKFLOWS.glob("*.yml"))


def _steps(job):
    return job.get("steps") or []


def _caches_pip(step):
    if "setup-python" not in str(step.get("uses", "")):
        return False
    return bool(str(step.get("with", {}).get("cache", "")).strip())


def _pip_installs(job):
    return any(
        any(marker in str(step.get("run", "")) for marker in INSTALLS_ON_THE_RUNNER)
        for step in _steps(job)
    )


@pytest.mark.parametrize("path", _workflows(), ids=lambda p: p.name)
def test_a_job_caches_pip_only_if_it_installs_pip(path):
    for name, job in (yaml.safe_load(path.read_text()).get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if any(_caches_pip(step) for step in _steps(job)):
            assert _pip_installs(job), (
                f"{path.name}:{name} caches pip and never installs with it. "
                "The post-step fails the job on a miss and copies someone "
                "else's entry on a hit."
            )


def test_the_shared_checks_do_not_cache():
    """The stages run in Docker. The input exists so the caller can say
    so -- repositories that install on the runner leave it alone."""
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    assert ci["jobs"]["checks"]["with"]["pip-cache"] is False


def test_the_weekly_snapshot_is_the_one_that_installs():
    """It is also the only job allowed to cache, and does not, because
    2.9 GB once a week is a third of the repository's budget."""
    job = yaml.safe_load((WORKFLOWS / "dependency-submission.yml").read_text())["jobs"][
        "submit-dependencies"
    ]
    assert _pip_installs(job)
    assert not any(_caches_pip(step) for step in _steps(job))
