"""A documentation-only PR must be able to satisfy the required checks.

The ruleset requires `checks / lint`, `checks / typecheck`, `checks / test` and
`checks / integration`. Those four contexts are produced by jobs INSIDE the
reusable workflow the `checks` job calls, so when `checks` is skipped for a
docs-only change the contexts are never created — not skipped, not passed,
ABSENT. GitHub then reports each one as "Expected — waiting for status to be
reported" and waits forever. Nothing is coming.

Found on #641, a documentation-only PR that went BLOCKED with every check that
could run passing. Every docs-only PR in this repository had the same problem,
and the only way out was an admin bypass.

So the docs-only path reports the same four contexts itself. A job's status
context is its NAME, and a name may contain a slash, which is what lets a plain
job stand in for one of the reusable workflow's.

The invariant these tests protect is that EXACTLY ONE of the two sets runs. If
both could run, a stub would race the real suite and either could report last; if
neither could, the PR is blocked again. The two conditions are therefore exact
negations of each other on the same output, which is the kind of thing an edit to
one side quietly breaks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(".github/workflows/ci.yml")

#: What the branch ruleset requires. Kept here as the literal list because the
#: ruleset lives in GitHub rather than the repository, so this file is the only
#: place the two can be compared by a human reading a diff.
REQUIRED_CONTEXTS = [
    "checks / lint",
    "checks / typecheck",
    "checks / test",
    "checks / integration",
]


@pytest.fixture(scope="module")
def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _normalise(condition: str) -> str:
    return " ".join(str(condition).split())


class TestTheStubReportsWhatIsRequired:
    def test_every_required_context_is_covered(self, jobs):
        contexts = jobs["docs-only-checks"]["strategy"]["matrix"]["context"]
        assert sorted(contexts) == sorted(REQUIRED_CONTEXTS)

    def test_the_job_name_is_the_matrix_context(self, jobs):
        """The context IS the name -- that is the whole mechanism."""
        assert jobs["docs-only-checks"]["name"] == "${{ matrix.context }}"

    def test_the_stub_does_nothing_but_report(self, jobs):
        """It must not be able to fail for a reason of its own.

        A stub that runs real work could fail and block the docs PR it exists to
        unblock.
        """
        steps = jobs["docs-only-checks"]["steps"]
        assert len(steps) == 1
        assert "uses" not in steps[0]
        assert steps[0]["run"].strip().startswith("echo")


class TestExactlyOneSetRuns:
    def test_the_conditions_are_negations_on_the_same_output(self, jobs):
        real = _normalise(jobs["checks"]["if"])
        stub = _normalise(jobs["docs-only-checks"]["if"])
        assert "needs.changes.outputs.code == 'true'" in real
        assert "needs.changes.outputs.code != 'true'" in stub

    def test_they_agree_on_everything_else(self, jobs):
        """Only the code test may differ.

        The draft guard in particular has to match: if the stub ran on drafts and
        the real suite did not, a draft could report the required contexts as
        passing and then be merged on a stub.
        """
        real = _normalise(jobs["checks"]["if"]).replace(
            "needs.changes.outputs.code == 'true'", "CODE"
        )
        stub = _normalise(jobs["docs-only-checks"]["if"]).replace(
            "needs.changes.outputs.code != 'true'", "CODE"
        )
        assert real == stub

    def test_both_wait_on_the_same_detection_job(self, jobs):
        assert jobs["checks"]["needs"] == ["changes"]
        assert jobs["docs-only-checks"]["needs"] == ["changes"]


class TestTheDetectionItselfIsUnchanged:
    def test_a_workflow_change_is_not_documentation(self):
        """Editing CI must run the suite, including this edit.

        `scripts/ci/docs-only.sh` is a deny-list precisely because an allow-list
        once had `.github/workflows/` on it, making a change to CI the one change
        CI never ran. This test fails if that regresses -- and it is why the fix
        for a docs-only problem arrives on a PR that is itself not docs-only.
        """
        script = Path("scripts/ci/docs-only.sh").read_text()
        assert ".github/workflows" not in script.split("code=$(")[1]

    def test_the_pre_push_hook_and_ci_ask_the_same_script(self):
        script = Path("scripts/ci/docs-only.sh")
        assert script.exists()
        ci = WORKFLOW.read_text()
        assert "scripts/ci/docs-only.sh" in ci
