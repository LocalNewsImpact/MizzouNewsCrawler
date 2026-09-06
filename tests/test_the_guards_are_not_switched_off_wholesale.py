"""`enable_selenium` marks a test, not a file.

The mark switches off two autouse guards (tests/conftest.py):
`disable_real_selenium`, which keeps SELENIUM_AVAILABLE false, and
`block_external_network`, which fails a unit test that reaches a
non-loopback host.

`tests/test_selenium_only_feature.py` carried it at module scope, so all
35 tests ran with both off. The ones whose fetch was not mocked went to
the real network and fell back to real headful Chrome:

    test_extract_content_normal_flow_for_non_selenium_only   177.5s
    test_extract_content_checks_extraction_method             42.7s

358 seconds for the file in the Selenium Headful Regression job, on
every pull request that touches any code. The 177-second one asserted
nothing at all -- it called extract_content and ended on a comment.

With the guards restored the same 35 tests take ten seconds, and they
test more: a mocked branch that silently falls through to the network is
not exercising the branch it names.
"""

import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

#: Marks that disable a guard rather than describe a test.
LOOSENING = ("enable_selenium", "allow_network")


def _module_level_marks(text: str) -> list[str]:
    """`pytestmark` assignments at column 0 -- the whole file."""
    found = []
    for line in text.splitlines():
        if not line.startswith("pytestmark"):
            continue
        for mark in LOOSENING:
            if mark in line:
                found.append(f"{mark}: {line.strip()}")
    return found


@pytest.mark.parametrize("path", sorted(TESTS.rglob("test_*.py")), ids=lambda p: p.name)
def test_no_file_switches_the_guards_off_for_everything(path):
    offenders = _module_level_marks(path.read_text(errors="ignore"))
    assert not offenders, (
        f"{path.name} disables a guard for every test in it: {offenders}. "
        "Mark the class or the test that needs it -- a file-wide mark hands "
        "the network to tests that only meant to mock a method."
    )


def test_the_headful_job_still_has_something_to_run():
    """scripts/ci/test-selenium.sh selects `-m enable_selenium` from this
    one file. If nothing carried the mark the job would collect nothing
    and pytest would exit 5."""
    text = (TESTS / "test_selenium_only_feature.py").read_text()
    assert re.search(r"^    pytestmark = pytest\.mark\.enable_selenium", text, re.M), (
        "no class in the file carries the mark; the headful job would "
        "select no tests and fail"
    )


def test_the_slow_test_asserts_something_now():
    """It called extract_content and ended on a comment, for 177 seconds."""
    text = (TESTS / "test_selenium_only_feature.py").read_text()
    start = text.index("def test_extract_content_normal_flow_for_non_selenium_only")
    body = text[start : text.index("\n    def ", start + 10)]
    assert "assert" in body, "the test still asserts nothing"
