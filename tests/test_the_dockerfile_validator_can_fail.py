"""The validator that could not fail.

`validate-dockerfile-deps.sh` counts missing files so a build breaks in
CI rather than eight minutes into Cloud Build. It counted them inside a
`while` loop on the right-hand side of a pipe, which bash runs in a
subshell: every increment landed in a process that then exited, the
parent's counter was still zero, and the script printed "All Dockerfile
dependencies exist" and returned 0 whatever it had found. It ran in CI
from January and never failed once, because it could not.

A test that only runs it against this repository -- where nothing is
missing -- passes either way. These give it something to find.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/validate-dockerfile-deps.sh"


def _run(cwd):
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=cwd, capture_output=True, text=True
    )


@pytest.fixture
def context(tmp_path):
    """A build context with one Dockerfile the script looks at."""
    (tmp_path / "requirements-base.txt").write_text("")
    (tmp_path / "src").mkdir()
    return tmp_path


def _dockerfile(context, body):
    (context / "Dockerfile.base").write_text(body)
    return context


def test_a_missing_source_fails(context):
    _dockerfile(context, "FROM python:3.11\nCOPY gone.txt ./\n")
    result = _run(context)
    assert result.returncode == 1, result.stdout
    assert "gone.txt" in result.stdout


def test_a_context_that_is_whole_passes(context):
    _dockerfile(context, "FROM python:3.11\nCOPY requirements-base.txt ./\n")
    assert _run(context).returncode == 0


def test_every_source_is_checked_not_only_the_first(context):
    """The instruction takes several sources and one destination. Reading
    only the first left the rest unchecked."""
    _dockerfile(context, "FROM python:3.11\nCOPY requirements-base.txt gone.txt ./\n")
    result = _run(context)
    assert result.returncode == 1
    assert "gone.txt" in result.stdout


def test_a_continued_line_is_one_instruction(context):
    """A COPY split across lines was read as two, and the half after the
    backslash was never looked at."""
    _dockerfile(context, "FROM python:3.11\nCOPY src/ \\\n     gone/ ./app/\n")
    result = _run(context)
    assert result.returncode == 1
    assert "gone/" in result.stdout


def test_a_stage_copy_is_not_looked_for_in_the_repository(context):
    """`COPY --from=builder` takes files out of an earlier build stage.
    The repository is not supposed to have them."""
    _dockerfile(context, "FROM python:3.11\nCOPY --from=builder /wheels /wheels\n")
    assert _run(context).returncode == 0


def test_the_destination_is_not_mistaken_for_a_source(context):
    _dockerfile(context, "FROM python:3.11\nCOPY requirements-base.txt /app/nope/\n")
    assert _run(context).returncode == 0


def test_a_build_step_artifact_is_not_reported_missing(context):
    """`models/productionmodel.pt` is 418 MB, lives in GCS and is fetched
    into the context by cloudbuild-ml-base.yaml. A checkout does not have
    it, and that is not a broken build."""
    _dockerfile(
        context,
        "FROM python:3.11\nCOPY --chown=a:b models/productionmodel.pt /app/models/\n",
    )
    result = _run(context)
    assert result.returncode == 0, result.stdout
    assert "Provided at build time" in result.stdout


def test_every_exemption_is_still_fetched_by_a_build_step():
    """An exemption that outlives the step justifying it is how a check
    stops checking. Each exempt path has to appear in a Cloud Build
    config that puts it in the context."""
    script = SCRIPT.read_text()
    listed = script.split("PROVIDED_AT_BUILD_TIME=(", 1)[1].split(")", 1)[0]
    exemptions = [
        line.strip().strip('"') for line in listed.splitlines() if line.strip()
    ]
    assert exemptions, "the list is the point; an empty one means the parse broke"
    configs = "\n".join(
        path.read_text() for path in (ROOT / "gcp/cloudbuild").glob("*.yaml")
    )
    for artifact in exemptions:
        assert artifact in configs, f"{artifact} is exempt and nothing fetches it"


def test_this_repository_passes():
    """The check as CI runs it. It has to still be true, or the fix
    turned a silent pass into a loud failure of something real."""
    assert _run(ROOT).returncode == 0


def test_every_dockerfile_here_is_one_the_script_checks():
    """A Dockerfile the script does not name is a Dockerfile nothing
    validates -- which is how enrichment and ci-base were missed."""
    named = {
        line.strip()
        for line in SCRIPT.read_text().splitlines()
        if line.strip().startswith("Dockerfile.")
    }
    on_disk = {p.name for p in ROOT.glob("Dockerfile.*") if p.is_file()}
    assert on_disk - named == set(), f"not validated: {sorted(on_disk - named)}"


def test_bash_is_what_runs_it():
    assert shutil.which("bash"), "the validator is a bash script"
