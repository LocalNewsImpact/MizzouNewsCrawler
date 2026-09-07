"""A red build that has nothing to do with the commit.

`scripts/ci/in-image` installs the requirements before every stage, and
one of them is fetched from github.com on every run:

    requirements-base.txt:80
    lnic-contracts @ https://github.com/.../archive/refs/tags/vX.Y.Z.tar.gz

So a gateway timeout from GitHub fails a stage that never ran, and
reports it as that stage. On PR #529 it read `checks / lint FAILURE`
with nothing linted:

    ERROR: HTTP error 504 while getting .../lnic-contracts/...v0.3.0.tar.gz
    make: *** [Makefile:152: lint] Error 1

pip does not retry it. A 504 is an HTTP response rather than a
connection error, so pip treats it as fatal and stops on the first one.

These read the script, because the runner is where it was already too
late.
"""

import re
from pathlib import Path

IN_IMAGE = Path(__file__).resolve().parent.parent / "scripts/ci/in-image"
TEXT = IN_IMAGE.read_text()


def test_the_install_is_retried():
    """Not once. The failure being guarded against is transient by
    definition, and one attempt cannot tell it from a real one."""
    assert "for attempt in 1 2 3" in TEXT
    body = TEXT[TEXT.index("for attempt in 1 2 3") :]
    assert "pip install" in body, "the retry must wrap the install itself"


def test_it_waits_longer_each_time():
    """A retry with no gap re-asks a service that is already failing."""
    assert re.search(r"sleep \$\(\(attempt \* \d+\)\)", TEXT)


def test_a_real_failure_still_fails_the_run():
    """A requirement that does not resolve, or a conflict, fails all
    three attempts and must still fail the build -- only later. Retrying
    for ever would turn a broken requirements file into a hung job."""
    assert "exit 1" in TEXT
    assert 'if [ "$attempt" = 3 ]' in TEXT


def test_the_stage_still_runs_after_a_successful_install():
    """`exec "$@"` is the whole point of the wrapper: the retry must not
    swallow the stage it exists to prepare for."""
    assert TEXT.rstrip().endswith('exec "$@"')


def test_the_requirement_this_guards_is_still_fetched_over_the_network():
    """If lnic-contracts ever moves to a registry or into the image, this
    guard is no longer load-bearing and the next author should know it
    was written for a URL that no longer exists."""
    base = (IN_IMAGE.parent.parent.parent / "requirements-base.txt").read_text()
    assert "lnic-contracts @ https://" in base
