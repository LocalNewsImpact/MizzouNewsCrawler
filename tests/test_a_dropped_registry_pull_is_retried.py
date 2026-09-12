"""A runner whose DNS did not answer must not fail the build.

On 2026-09-12 `checks / lint` on PR #564 failed after 25 seconds with
`lookup ghcr.io on 127.0.0.53:53: i/o timeout` -- reported as a lint
failure, though ruff never ran: `make ci-image` pulled the image once and
`docker pull` died on a name lookup. Six jobs begin with that pull.

The script is bash, so these drive it with fake `docker` and `gh` on the
PATH and assert on what it did.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/ci/pull-image.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _fake_docker(tmp_path, script):
    """A `docker` on PATH that does what the test says, and a log of calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text("#!/usr/bin/env bash\n" + script)
    (bin_dir / "docker").chmod(0o755)
    (bin_dir / "gh").write_text("#!/usr/bin/env bash\necho faketoken\n")
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def _run(tmp_path, docker_script, attempts="4", image="ghcr.io/x/ci:abc"):
    bin_dir = _fake_docker(tmp_path, docker_script)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PULL_ATTEMPTS": attempts,
        "GITHUB_TOKEN": "t",
        "GITHUB_ACTOR": "u",
        "CALLS": str(tmp_path / "calls"),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), image],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )


COUNTING = """
printf '%s\\n' "$*" >> "$CALLS"
[ "$1" = "login" ] && exit 0
n=$(grep -c '^pull' "$CALLS" || true)
"""


def test_a_pull_that_works_first_time_does_not_retry(tmp_path):
    result = _run(tmp_path, COUNTING + "exit 0\n")
    assert result.returncode == 0
    calls = (tmp_path / "calls").read_text().splitlines()
    assert [c.split()[0] for c in calls] == ["login", "pull"]


def test_a_dropped_connection_is_retried_until_it_works(tmp_path):
    """The exact failure: a name lookup that timed out. It succeeded when
    the job was re-run by hand, which is the definition of worth
    retrying."""
    script = COUNTING + """
if [ "$n" -lt 3 ]; then
    echo 'Error response from daemon: Get "https://ghcr.io/v2/": dial tcp: '\\
         'lookup ghcr.io on 127.0.0.53:53: read udp: i/o timeout' >&2
    exit 1
fi
exit 0
"""
    result = _run(tmp_path, script)
    assert result.returncode == 0
    pulls = [
        c for c in (tmp_path / "calls").read_text().splitlines() if c.startswith("pull")
    ]
    assert len(pulls) == 3
    assert "retrying in" in result.stderr


def test_it_gives_up_rather_than_holding_a_runner_forever(tmp_path):
    result = _run(tmp_path, COUNTING + "echo 'i/o timeout' >&2\nexit 1\n", attempts="2")
    assert result.returncode == 1
    assert "failed 2 times" in result.stderr
    pulls = [
        c for c in (tmp_path / "calls").read_text().splitlines() if c.startswith("pull")
    ]
    assert len(pulls) == 2


def test_a_refusal_is_not_retried(tmp_path):
    """`denied`, `unauthorized`, `not found`: the registry answered, and
    the answer is the same three more times. Retrying it spends three
    minutes of a runner and buries the real message."""
    script = COUNTING + "echo 'denied: permission_denied: write_package' >&2\nexit 1\n"
    result = _run(tmp_path, script)
    assert result.returncode == 1
    assert "was refused, not dropped" in result.stderr
    pulls = [
        c for c in (tmp_path / "calls").read_text().splitlines() if c.startswith("pull")
    ]
    assert len(pulls) == 1


def test_a_failed_login_is_retried_too(tmp_path):
    """The login is a network call to the same host and failed the same
    way. Retrying only the pull leaves half the failure uncovered."""
    script = """
printf '%s\\n' "$*" >> "$CALLS"
n=$(grep -c '^login' "$CALLS" || true)
if [ "$1" = "login" ] && [ "$n" -lt 2 ]; then
    echo 'i/o timeout' >&2
    exit 1
fi
exit 0
"""
    result = _run(tmp_path, script)
    assert result.returncode == 0
    logins = [
        c
        for c in (tmp_path / "calls").read_text().splitlines()
        if c.startswith("login")
    ]
    assert len(logins) == 2


def test_every_image_target_goes_through_the_retry():
    """Two targets pull an image, and a second one added later would
    otherwise reintroduce the single-attempt pull."""
    makefile = (ROOT / "Makefile").read_text()
    pulls = [
        line
        for line in makefile.splitlines()
        if "docker pull" in line and not line.strip().startswith("#")
    ]
    assert pulls == [], f"a bare docker pull is not retried: {pulls}"
    assert makefile.count("scripts/ci/pull-image.sh $(") == 2
