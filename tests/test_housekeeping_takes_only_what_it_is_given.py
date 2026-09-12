"""Housekeeping must never touch a record nobody asked about.

It exists to carry the handful of records a review decision rewound
through the rest of the pipeline. Every pipeline stage selects by STATUS,
and a rewound record shares its status with the whole backlog -- so a
stage told nothing takes everything.

That is not hypothetical. A housekeeping run pointed at the cluster began
extracting 4,802 links when the dispositions accounted for 45: 49 links
moved to `wire` by the reconciler and 45 re-queued by hand. The rest was
a pre-existing extraction backlog that no reviewer had said anything
about, being fetched from publishers one Selenium page at a time.

The enrichment step had already been guarded, because it spends money.
These tests exist because "free" was the wrong test and scope was the
requirement -- extraction and classification cost publisher requests and
processing time, and neither is housekeeping's to spend on records
outside its remit.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "k8s/argo/housekeeping-workflow.yaml"
EXTRACTION = ROOT / "src/cli/commands/extraction.py"
CLASSIFIER = ROOT / "src/services/classification_service.py"


# --- the stages can be told which records ------------------------------------


def test_extraction_can_be_told_which_records():
    """Without this there is no way to express "these links and no
    others", and `extract` takes every link awaiting extraction. The
    records come from `pipeline_rework`, not a file: working state lives
    in the database, and a file and the database disagree the moment a
    run dies halfway."""
    body = EXTRACTION.read_text()
    assert '"--rework"' in body
    assert "_links_owed_a_fetch" in body
    assert "ids_file" not in body, "working state does not travel in files"


def test_the_rework_set_actually_narrows_the_query():
    """A flag that is parsed and never reaches the WHERE clause reads as
    a working filter and is not one."""
    body = EXTRACTION.read_text()
    assert "AND cl.id = ANY(:link_ids)" in body
    assert 'params["link_ids"] = rework_ids' in body


def test_nothing_owed_means_nothing_not_everything():
    """ "No filter" and "no records" are opposite instructions. Conflating
    them is how a targeted run becomes a sweep."""
    body = EXTRACTION.read_text()
    branch = body.split('if getattr(args, "rework", False) is True:')[1]
    branch = branch.split('if getattr(args, "dataset"')[0]
    assert "if not rework_ids:" in branch
    # The batch contract is a dict, so the early exit is an empty batch --
    # a bare `return []` here broke every caller that reads `["processed"]`.
    assert 'return {"processed": 0}' in branch


def test_classification_can_be_given_an_id_list():
    body = CLASSIFIER.read_text()
    assert "only_article_ids" in body
    assert "Article.id.in_(list(only_article_ids))" in body


def test_an_empty_classification_id_list_selects_nothing():
    """`only_article_ids=[]` must mean none, never all. The difference is
    a `is not None` check, and getting it wrong is silent."""
    body = CLASSIFIER.read_text()
    guard = body.split("only_article_ids is not None")[1].split("if statuses")[0]
    assert "return []" in guard, "an empty id list falls through to the full query"


# --- and the workflow uses them ----------------------------------------------


@pytest.fixture(scope="module")
def stages():
    template = yaml.safe_load(WORKFLOW.read_text())
    return {t["name"]: t for t in template["spec"]["templates"]}


@pytest.mark.parametrize("stage", ["extraction-step", "classify-step", "enrich-step"])
def test_every_working_stage_is_told_which_records(stages, stage):
    """The command each stage runs must read `pipeline_rework`. A stage
    invoked without `--rework` selects by status alone, which is the
    whole backlog."""
    command = " ".join(stages[stage]["container"]["command"])
    assert "--rework" in command, (
        f"{stage} runs without --rework, so it takes every record at its "
        "status rather than the ones a decision rewound"
    )


def test_a_run_with_nothing_owed_stops_before_starting_a_stage(stages):
    """The first step counts what is owed and every stage is gated on it.
    An empty night costs a few seconds, not three pods."""
    entry = stages["housekeeping"]
    names = [s[0]["name"] for s in entry["steps"]]
    assert names[0] == "anything-owed"
    for step in entry["steps"][1:]:
        assert "anything-owed" in step[0].get("when", ""), step[0]["name"]


def test_it_finishes_before_the_bigquery_sync():
    cron = yaml.safe_load(
        (ROOT / "k8s/argo/housekeeping-cronworkflow.yaml").read_text()
    )
    deadline = cron["spec"]["workflowSpec"]["activeDeadlineSeconds"]
    hour = int(cron["spec"]["schedule"].split()[1])
    assert hour + deadline / 3600 <= 7, "a run could still be going at the 07:00 sync"


def test_the_schedule_is_declared_suspended_until_the_end_to_end_run_passes():
    """The suspend lives in the manifest, not in a cluster patch. A patch
    is invisible in the repository and undone by whichever apply next
    carries the field; the first run of this workflow swept 4,802 links.
    Resuming is a reviewed change to the file. (Delete this test when the
    plan's step 8 has passed and the line is removed.)"""
    cron = yaml.safe_load(
        (ROOT / "k8s/argo/housekeeping-cronworkflow.yaml").read_text()
    )
    assert cron["spec"]["suspend"] is True


def test_no_stage_runs_a_bare_sweeping_command(stages):
    """The specific commands that take everything: `extract` with no ids,
    `analyze` with no ids, `enrich run` at all (its targeted form is
    `enrich backfill --ids-file`)."""
    for name, stage in stages.items():
        container = stage.get("container")
        if not container:
            continue
        command = " ".join(container["command"])
        if re.search(r"\benrich\b", command):
            assert (
                "backfill" in command and " run " not in f" {command} "
            ), f"{name} runs `enrich run`, which sweeps every article at labeled"
        if re.search(r"\bextract\b|\banalyze\b|\bbackfill\b", command):
            assert "--rework" in command, f"{name} sweeps by status"
