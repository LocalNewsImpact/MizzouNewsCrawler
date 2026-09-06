"""The migration job fails when the database is not at the head it carries.

`alembic current` PRINTS a revision. It was the whole of the
entrypoint's verification, and printing is not checking: a run that
applied nothing, or that stopped short of head, printed a revision and
exited 0 exactly like a run that did the work. The job's log ended
"Migration completed successfully!" either way.

That is not the bug that sent eight days of migrations to the retired
instance -- that database was at head too, and what closes it is every
manifest naming its own instance
(tests/test_no_retired_db_instance.py). This is the neighbouring silent
success, and it is the one a check can catch.

The entrypoint is run here as a script with `alembic` replaced by a stub,
because the assertion is shell and shell is where it can be wrong.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parent.parent / "scripts/migrations/entrypoint.sh"


def _fake_alembic(tmp_path, current, heads, upgrade_exit=0):
    """A stub `alembic` that answers `current`, `heads` and `upgrade`."""
    script = tmp_path / "alembic"
    script.write_text(
        "#!/bin/bash\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in\n'
        f"    current) echo '{current}'; exit 0 ;;\n"
        f"    heads)   echo '{heads}'; exit 0 ;;\n"
        f"    upgrade) exit {upgrade_exit} ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _run(tmp_path, current, heads, upgrade_exit=0):
    """The entrypoint, against a stub alembic and a fake /app."""
    app = tmp_path / "app"
    (app / "alembic" / "versions").mkdir(parents=True)
    (app / "alembic.ini").write_text("[alembic]\n")
    (app / "alembic" / "versions" / "0001_x.py").write_text("")
    _fake_alembic(tmp_path, current, heads, upgrade_exit)

    body = ENTRYPOINT.read_text().replace("cd /app", f"cd {app}")
    runner = tmp_path / "entrypoint.sh"
    runner.write_text(body)
    runner.chmod(runner.stat().st_mode | stat.S_IEXEC)

    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "USE_CLOUD_SQL_CONNECTOR": "true",
        "CLOUD_SQL_INSTANCE": "project:region:instance",
        "DATABASE_USER": "u",
        "DATABASE_PASSWORD": "p",
        "DATABASE_NAME": "mizzou",
    }
    return subprocess.run(
        ["bash", str(runner)], capture_output=True, text=True, env=env
    )


def test_at_head_succeeds(tmp_path):
    done = _run(tmp_path, current="abc123 (head)", heads="abc123 (head)")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "the database is at head" in done.stdout


def test_short_of_head_fails(tmp_path):
    """The upgrade reported success and left the database a revision
    behind. That used to print and exit 0."""
    done = _run(tmp_path, current="abc123", heads="def456 (head)")
    assert done.returncode != 0
    assert "not at the head this image carries" in done.stdout
    assert "applied: abc123" in done.stdout
    assert "wanted:  def456" in done.stdout


def test_the_instance_is_named_when_it_fails(tmp_path):
    """Which database it was talking to is the first question asked, and
    the log did not answer it."""
    done = _run(tmp_path, current="abc123", heads="def456")
    assert "project:region:instance" in done.stdout


def test_the_instance_is_named_when_it_succeeds(tmp_path):
    done = _run(tmp_path, current="abc123", heads="abc123")
    assert "instance: project:region:instance" in done.stdout
    assert "database: mizzou" in done.stdout


def test_an_unreadable_revision_is_a_failure_not_a_pass(tmp_path):
    """Empty on either side means the check itself could not run, and a
    check that cannot run must not report success."""
    done = _run(tmp_path, current="", heads="def456")
    assert done.returncode != 0
    assert "could not read the revision" in done.stdout


@pytest.mark.parametrize("exit_code", [1, 2])
def test_a_failed_upgrade_still_stops_the_job(tmp_path, exit_code):
    """`set -e` did this before and must keep doing it."""
    done = _run(tmp_path, current="abc", heads="abc", upgrade_exit=exit_code)
    assert done.returncode != 0
    assert "the database is at head" not in done.stdout
