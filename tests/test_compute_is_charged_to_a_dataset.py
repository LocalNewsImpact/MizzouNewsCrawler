"""Every workload that spends compute stamps its dataset on the POD.

GKE cost allocation is enabled on `mizzou-cluster`
(`costManagementConfig.enabled=True`) and attributes node cost by **pod**
label. `dataset` was a workflow PARAMETER, and in
`dataset-pipeline-template.yaml` a label on the CronWorkflow object -- neither
is a pod, so nothing carrying the dataset ever reached the billing export.
Compute could be split by `stage` and never by dataset.

Two further rules this pins, both learned the hard way on 2026-09-19:

- **Extraction never runs unscoped.** The work queue draws from every dataset
  when given none, so an omitted `--dataset` pulls another corpus's backlog and
  charges it to the wrong place, or to nowhere.
- **Extraction goes through the work queue.** `USE_WORK_QUEUE=true` is what
  makes the queue ration by domain -- one domain and at most three articles per
  request, 60s cooldown. A hand-written Job that looped `--source` to
  exhaustion drew 429s and 403s from a publisher.

A GCP label value must be lowercase, so the label is wrapped in `sprig.lower`:
the real ids are `WSU-Washington-State` and `Mizzou-Missouri-State`, and
passing those raw is rejected -- which looks identical to having no label.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ARGO = Path("k8s/argo")
BASE = ARGO / "base-pipeline-workflow.yaml"

#: Every template that puts a pod on a node and therefore costs money.
#:
#: `verification-step` was absent until 2026-09-19: it took no dataset, the DAG
#: passed none, and `verify-urls` had no `--dataset` flag, so a run launched for
#: one corpus verified every corpus and its compute belonged to nobody.
#: `candidate_links.dataset_id` is recorded at insert, so the scope was always
#: there to use.
COMPUTE_STEPS = ("discovery-step", "verification-step", "extraction-step")


def _templates(path: Path) -> dict[str, dict]:
    # The manifests carry `${CRAWLER_TAG}` placeholders, which are not YAML's
    # problem -- they sit inside quoted scalars -- so this parses as-is.
    docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
    out: dict[str, dict] = {}
    for doc in docs:
        for tpl in doc.get("spec", {}).get("templates", []):
            out[tpl["name"]] = tpl
    return out


@pytest.fixture(scope="module")
def base():
    return _templates(BASE)


@pytest.mark.parametrize("name", COMPUTE_STEPS)
def test_a_compute_step_labels_its_pod_with_the_dataset(base, name):
    labels = base[name].get("metadata", {}).get("labels", {})
    assert "dataset" in labels, (
        f"{name} spends compute with no `dataset` pod label, so its cost "
        f"cannot be attributed. Labels present: {sorted(labels)}"
    )


@pytest.mark.parametrize("name", COMPUTE_STEPS)
def test_the_label_is_lowercased(base, name):
    value = base[name]["metadata"]["labels"]["dataset"]
    assert "sprig.lower" in value, (
        f"{name} passes the dataset id through unchanged. A GCP label value "
        "must be lowercase; `WSU-Washington-State` is rejected."
    )


@pytest.mark.parametrize("name", COMPUTE_STEPS)
def test_the_step_takes_a_dataset_parameter(base, name):
    names = [p["name"] for p in base[name].get("inputs", {}).get("parameters", [])]
    assert "dataset" in names, f"{name} cannot label what it is not given"


def test_extraction_passes_the_dataset_to_the_command(base):
    args = " ".join(base["extraction-step"]["container"].get("args", []))
    assert "--dataset" in args, "extraction must never run unscoped"
    assert "{{inputs.parameters.dataset}}" in args


def test_extraction_uses_the_work_queue(base):
    env = {
        e["name"]: e.get("value")
        for e in base["extraction-step"]["container"].get("env", [])
    }
    assert env.get("USE_WORK_QUEUE") == "true", (
        "extraction must go through the work queue, which rations by domain. "
        "Bypassing it is what drew 429s from a publisher."
    )
    assert env.get("WORK_QUEUE_URL")


def test_no_argo_manifest_turns_the_work_queue_off():
    offenders = []
    for path in ARGO.rglob("*.yaml"):
        text = path.read_text()
        # Tolerate the string inside a comment; catch it as a real setting.
        for match in re.finditer(r"USE_WORK_QUEUE\s*\n?\s*value:\s*\"?(\w+)", text):
            if match.group(1).lower() != "true":
                offenders.append(f"{path}: {match.group(1)}")
    assert not offenders, f"the work queue is disabled in: {offenders}"


class TestTheExtractionOnlyTemplate:
    """A curated dataset needs extraction without discovery or verification."""

    @pytest.fixture(scope="class")
    def doc(self):
        path = ARGO / "dataset-extraction-workflow.yaml"
        assert path.exists(), "no extraction-only entry point"
        return yaml.safe_load(path.read_text())

    def test_the_dataset_has_no_default(self, doc):
        params = {p["name"]: p for p in doc["spec"]["arguments"]["parameters"]}
        assert "dataset" in params
        assert "value" not in params["dataset"], (
            "a default dataset is a dataset nobody chose, and the work queue "
            "would draw from every corpus"
        )

    def test_it_reuses_the_tested_step_rather_than_copying_it(self, doc):
        text = (ARGO / "dataset-extraction-workflow.yaml").read_text()
        assert "templateRef" in text
        assert "news-pipeline-template" in text
        # A copied env block is one that drifts: the work-queue setting and
        # the retry strategy must come from the single definition. Comment
        # lines are stripped first -- the file explains the work queue in
        # prose, which is not the same as configuring it.
        code = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )
        assert (
            "USE_WORK_QUEUE" not in code
        ), "the env belongs to extraction-step, not to this file"

    def test_it_declares_its_service_account(self, doc):
        # A `--from workflowtemplate` submit otherwise defaults to `default`,
        # which has no Workload Identity and dies on cloudsql.instances.get.
        assert doc["spec"]["serviceAccountName"] == "argo-workflow"

    def test_it_runs_more_than_one_worker_on_the_queue(self, doc):
        tpl = doc["spec"]["templates"][0]
        step = tpl["steps"][0][0]
        assert "withSequence" in step, "one worker does not distribute domains"
        assert step["templateRef"]["template"] == "extraction-step"


def test_verification_is_scoped_to_the_dataset_it_is_given():
    """The step passes `--dataset` to the command, not just to the label.

    A pod label alone would attribute the cost correctly and still verify the
    wrong corpus. Both halves have to be there: the command scopes the work,
    the label charges it.
    """
    base = _templates(BASE)
    command = base["verification-step"]["container"]["command"]
    assert "--dataset" in command, "verification must not run unscoped"
    assert command[command.index("--dataset") + 1] == ("{{inputs.parameters.dataset}}")


def test_the_dag_gives_every_compute_step_its_dataset():
    """A declared parameter nobody passes is still an unscoped run."""
    base = _templates(BASE)
    dag = base["pipeline"]["dag"]["tasks"]
    by_template = {t["template"]: t for t in dag}
    for step in COMPUTE_STEPS:
        task = by_template[step]
        passed = [p["name"] for p in task.get("arguments", {}).get("parameters", [])]
        assert "dataset" in passed, (
            f"the DAG runs {step} without passing a dataset, so its label "
            "renders empty and its work is unscoped"
        )


def test_the_verification_service_filters_on_the_dataset():
    """The flag has to reach the query, not just the constructor.

    The service accepted `dataset_id` for a long time and used it only for the
    job row; `get_unverified_urls` selected every dataset's links regardless.
    """
    import inspect

    from src.services.url_verification import URLVerificationService

    source = inspect.getsource(URLVerificationService.get_unverified_urls)
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "self.dataset_id" in code
    assert "cl.dataset_id = :dataset_id" in code


def test_the_verify_command_offers_the_flag():
    import argparse

    from src.cli.commands.verification import add_verification_parser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    verify = add_verification_parser(sub)
    flags = {option for action in verify._actions for option in action.option_strings}
    assert "--dataset" in flags
