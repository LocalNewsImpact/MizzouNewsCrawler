"""The step that decides whether a night runs at all.

`anything-owed-step` is an Argo `script` template: a few lines of Python
inlined in YAML, which no test imports and no linter reads. Its stdout IS
the gate -- `when: "{{steps.anything-owed.outputs.result}} != 0"` on every
stage -- so what it prints decides whether three pods start.

Nothing had ever run it. These extract the script out of the manifest and
execute it against real PostgreSQL, because the two ways it can fail are
both invisible in the YAML: it can raise (the whole run dies at step 0),
and it can print something the gate cannot compare (every stage runs on an
empty night, or none runs on a full one).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / "k8s/argo/housekeeping-workflow.yaml"
REVISION = "x9y0z1a2b3c4"


def _pg_url():
    url = os.environ.get("ENRICHMENT_PG_URL") or os.environ.get("DATABASE_URL", "")
    return url if url.startswith(("postgresql://", "postgres://")) else None


pytestmark = pytest.mark.skipif(_pg_url() is None, reason="needs PostgreSQL")


def _template(name):
    doc = yaml.safe_load(WORKFLOW.read_text())
    return next(t for t in doc["spec"]["templates"] if t["name"] == name)


def _gate_expression():
    """The `when` every stage carries, as written."""
    housekeeping = _template("housekeeping")
    gates = {
        step["when"]
        for group in housekeeping["steps"]
        for step in group
        if "when" in step
    }
    assert len(gates) == 1, f"stages disagree about the gate: {gates}"
    return gates.pop()


@pytest.fixture()
def db(tmp_path):
    url = _pg_url()
    env = {**os.environ, "DATABASE_URL": url, "USE_CLOUD_SQL_CONNECTOR": "false"}
    assert (
        subprocess.run(
            ["alembic", "upgrade", REVISION],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        ).returncode
        == 0
    )
    engine = sa.create_engine(url)
    # The WHOLE table, not this test's rows. The guard counts every
    # outstanding row in the database -- one number for the run, not one
    # per dataset or per caller -- so a test asserting an exact count has
    # to own the table. One row left behind anywhere starts all three
    # stages, which is worth knowing about the gate.
    with engine.begin() as c:
        c.execute(sa.text("TRUNCATE pipeline_rework"))
    yield engine
    with engine.begin() as c:
        c.execute(sa.text("TRUNCATE pipeline_rework"))
    engine.dispose()


def _run_the_guard(tmp_path):
    """Exactly the source the pod runs, as the pod runs it: `python` on a
    file, from a directory that is not the project root -- which is what
    an Argo `script` template does. `PYTHONPATH` is what makes `import
    src` work there, and the image sets it."""
    script = tmp_path / "guard.py"
    script.write_text(_template("anything-owed-step")["script"]["source"])
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
        env={
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "USE_CLOUD_SQL_CONNECTOR": "false",
        },
    )


def _owe(engine, n):
    with engine.begin() as c:
        for i in range(n):
            c.execute(
                sa.text(
                    "INSERT INTO pipeline_rework (record_type, record_id, stage, "
                    "requested_by) VALUES ('article', :id, 'classify', 'guard')"
                ),
                {"id": f"guard-{i}"},
            )


def test_it_runs_at_all(db, tmp_path):
    """Step 0 of every night. If it raises, nothing else happens and the
    run is reported as failed."""
    result = _run_the_guard(tmp_path)
    assert result.returncode == 0, result.stderr


def test_an_empty_table_prints_a_bare_zero(db, tmp_path):
    """`0`, alone, on one line. The gate is a textual substitution into
    `<result> != 0`: an empty string makes that ` != 0`, which is a
    syntax error, and a chatty script makes it nonsense."""
    out = _run_the_guard(tmp_path).stdout
    assert out.strip() == "0"
    assert len(out.strip().splitlines()) == 1


def test_a_populated_table_prints_the_count(db, tmp_path):
    _owe(db, 3)
    assert _run_the_guard(tmp_path).stdout.strip() == "3"


def test_it_counts_only_outstanding_rows(db, tmp_path):
    """A closed row is history. Counting it would run every stage for
    work that was already done, every night, forever."""
    _owe(db, 2)
    with db.begin() as c:
        c.execute(
            sa.text(
                "UPDATE pipeline_rework SET done_at = now(), outcome = 'classified' "
                "WHERE requested_by = 'guard' AND record_id = 'guard-0'"
            )
        )
    assert _run_the_guard(tmp_path).stdout.strip() == "1"


@pytest.mark.parametrize("owed", [0, 1, 7])
def test_the_gate_decides_the_way_the_stages_need(db, tmp_path, owed):
    """The gate, evaluated the way Argo evaluates it: substitute the
    step's result into the expression as TEXT, then compare. `0 != 0` is
    false and the stages are omitted; `7 != 0` is true and they run.

    This is the assertion that was missing. Every earlier test read the
    `when` string out of the YAML and confirmed it was the string
    somebody wrote."""
    _owe(db, owed)
    result = _run_the_guard(tmp_path).stdout.strip()
    expression = _gate_expression().replace(
        "{{steps.anything-owed.outputs.result}}", result
    )
    left, right = expression.split("!=")
    runs = int(left.strip()) != int(right.strip())
    assert runs == (owed != 0), f"{expression!r} decided {runs} with {owed} owed"


def test_a_closed_row_stops_the_night(db, tmp_path):
    """The cost of one number for the whole run: a row nobody closed makes
    tonight start extraction, classification and enrichment, each finding
    nothing. Cheap, not free -- and it is why a stage that handles a
    record must close its row."""
    _owe(db, 1)
    assert _run_the_guard(tmp_path).stdout.strip() == "1"
    with db.begin() as c:
        c.execute(
            sa.text(
                "UPDATE pipeline_rework SET done_at = now(), outcome = 'classified'"
            )
        )
    assert _run_the_guard(tmp_path).stdout.strip() == "0"


# --- the commands the manifest actually runs ------------------------------------


def _stage_commands():
    """Every stage's command, with the caller's parameters substituted.

    Read out of the manifest rather than restated, so a flag renamed in
    the CLI, or a parameter a step stops passing, fails here. Nothing else
    connects the YAML to the code: the manifest is applied by kubectl,
    which validates none of it, and Argo checks the parameter wiring but
    not whether `extract` has a `--rework` flag.
    """
    doc = yaml.safe_load(WORKFLOW.read_text())
    templates = {t["name"]: t for t in doc["spec"]["templates"]}
    housekeeping = templates["housekeeping"]
    defaults = {
        p["name"]: p["value"]
        for p in housekeeping["inputs"]["parameters"]
        if "value" in p
    }

    commands = []
    for group in housekeeping["steps"]:
        for step in group:
            template = templates[step["template"]]
            container = template.get("container")
            if not container:
                continue
            passed = {
                p["name"]: p["value"]
                for p in (step.get("arguments") or {}).get("parameters", [])
            }
            rendered = []
            for part in container["command"]:
                part = str(part)
                for name, value in passed.items():
                    part = part.replace(f"{{{{inputs.parameters.{name}}}}}", value)
                for name, value in defaults.items():
                    part = part.replace(f"{{{{inputs.parameters.{name}}}}}", value)
                rendered.append(part)
            commands.append((step["name"], rendered))
    return commands


STAGE_COMMANDS = _stage_commands()


def test_the_manifest_names_every_stage():
    assert [name for name, _ in STAGE_COMMANDS] == ["extract", "classify", "enrich"]


@pytest.mark.parametrize(
    "name,command", STAGE_COMMANDS, ids=[n for n, _ in STAGE_COMMANDS]
)
def test_every_stage_command_runs_with_nothing_owed(db, tmp_path, name, command):
    """The command line the pod runs, run. With an empty table each stage
    must do nothing and exit 0.

    Nothing had ever executed these. The manifest passed `--rework` to
    three commands and was applied to production, and the only checks were
    string comparisons against the same YAML."""
    assert all("{{" not in part for part in command), f"unsubstituted: {command}"
    result = subprocess.run(
        [sys.executable, *command[1:]] if command[0] == "python" else command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=900,
        env={
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "USE_CLOUD_SQL_CONNECTOR": "false",
            "ENRICHMENT_SPEND_CEILING_USD": "10",
        },
    )
    assert (
        result.returncode == 0
    ), f"{name}: {result.stdout[-800:]}{result.stderr[-800:]}"


@pytest.mark.parametrize(
    "name,command", STAGE_COMMANDS, ids=[n for n, _ in STAGE_COMMANDS]
)
def test_every_stage_command_carries_rework(name, command):
    """The one flag that decides scope. Without it each of these takes the
    whole backlog: 4,802 links, 450 articles, 85,189 candidates for
    enrichment."""
    assert "--rework" in command


def test_no_stage_asks_for_a_flag_the_cli_does_not_have():
    """A flag renamed in the CLI leaves the manifest passing one that no
    longer exists, and argparse exits 2 -- at 03:00, in a pod."""
    for name, command in STAGE_COMMANDS:
        flags = [part for part in command if part.startswith("--")]
        help_text = subprocess.run(
            [sys.executable, *command[1 : command.index("--rework")], "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        ).stdout
        for flag in flags:
            assert flag in help_text, f"{name}: {flag} is not a flag of that command"
