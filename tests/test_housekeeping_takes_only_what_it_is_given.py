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


# --- the command settles what it read, not just the function --------------------


def _one_link_batch(env, link_id):
    """Drive one candidate link through the mocked batch loop."""
    from unittest.mock import Mock

    candidate = Mock()
    candidate.fetchall.return_value = [
        (link_id, "https://example.com/a", "Src", "article", "Example", None)
    ]
    empty = Mock()
    empty.fetchall.return_value = []
    empty.scalar.return_value = None
    empty.rowcount = 0
    served = {"batch": False}

    def execute(*args, **kwargs):
        sql = str(args[0]) if args else ""
        if "SELECT cl.id, cl.url, cl.source, cl.status" in sql and not served["batch"]:
            served["batch"] = True
            return candidate
        return empty

    env.session.execute.side_effect = execute
    env.extractor.extract_content.return_value = {
        "title": "T",
        "content": "Body about county services. " * 10,
        "author": "A",
        "publish_date": "2025-09-20T10:00:00",
        "metadata": {"source": "test"},
    }


def test_the_batch_settles_the_fetches_it_was_given():
    """`_settle_fetches` existed, was tested on its own, and was never
    called: the batch read the owed links and closed none of them, so a
    fetched link stayed "owed" forever and the nightly guard fired on
    nothing. The test that proves a function works is not the test that
    proves the command uses it."""
    from unittest.mock import patch

    from src.cli.commands.extraction import handle_extraction_command
    from tests.test_extraction_command import _build_args, mocked_extraction_env

    args = _build_args()
    args.rework = True
    with (
        mocked_extraction_env() as env,
        patch(
            "src.cli.commands.extraction._links_owed_a_fetch",
            return_value=["link-1"],
        ),
        patch(
            "src.cli.commands.extraction._settle_fetches", return_value=(1, 1)
        ) as settle,
    ):
        _one_link_batch(env, "link-1")
        assert handle_extraction_command(args) == 0
        settle.assert_called_once()
        assert settle.call_args.args[1] == ["link-1"]


def test_without_rework_nothing_is_settled_and_nothing_is_read():
    """The pipeline's own `extract` must not read or write the rework
    table: it is not housekeeping and its links owe nothing."""
    from unittest.mock import patch

    from src.cli.commands.extraction import handle_extraction_command
    from tests.test_extraction_command import _build_args, mocked_extraction_env

    args = _build_args()
    args.rework = False
    with (
        mocked_extraction_env() as env,
        patch("src.cli.commands.extraction._links_owed_a_fetch") as owed,
        patch("src.cli.commands.extraction._settle_fetches") as settle,
    ):
        _one_link_batch(env, "link-1")
        assert handle_extraction_command(args) == 0
        owed.assert_not_called()
        settle.assert_not_called()


def test_a_mock_for_args_does_not_switch_rework_on():
    """`Mock().rework` is a truthy Mock. `getattr(args, "rework", False)`
    read as truthiness walked every extraction test into the rework
    branch; the check is `is True`."""
    from unittest.mock import Mock, patch

    from src.cli.commands.extraction import handle_extraction_command
    from tests.test_extraction_command import _build_args, mocked_extraction_env

    args = _build_args()
    assert isinstance(args.rework, Mock)
    with (
        mocked_extraction_env() as env,
        patch("src.cli.commands.extraction._links_owed_a_fetch") as owed,
    ):
        _one_link_batch(env, "link-1")
        handle_extraction_command(args)
        owed.assert_not_called()


# --- each stage queues the next ----------------------------------------------------


def test_extraction_queues_classification_for_the_article_it_made():
    """The reconciler cannot: the article does not exist until the fetch."""
    body = EXTRACTION.read_text()
    settle = body.split("def _settle_fetches(")[1].split("\ndef ")[0]
    assert "'article', a.id, 'classify'" in settle
    assert "a.status IN ('cleaned', 'local')" in settle, "only a classifiable article"
    assert "ON CONFLICT DO NOTHING" in settle, "a duplicate request is the same request"


def test_classification_queues_enrichment_for_what_it_labelled():
    body = CLASSIFIER.read_text()
    settle = body.split("def _settle_rework(")[1].split("\n    def ")[0]
    assert "'article', r.record_id, 'enrich'" in settle
    assert "ON CONFLICT DO NOTHING" in settle


def test_enrichment_is_the_end_of_the_chain():
    """Nothing after `enriched`; a settle that queued more would loop."""
    body = (ROOT / "src/enrichment/repository.py").read_text()
    settle = body.split("def settle_enrichment_rework(")[1].split("\ndef ")[0]
    assert "INSERT INTO pipeline_rework" not in settle
