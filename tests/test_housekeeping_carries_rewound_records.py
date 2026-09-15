"""The daily workflow that carries a rewound record to its terminal status.

Not a new pipeline: the same stages, in the same order, selecting on the
same statuses, run small and daily so a record whose status a reviewer
changed still reaches the end while the production crons are suspended.
With the crons running it finds nothing to do, which is correct rather
than wasteful.

What these assert is the wiring, because the failure mode is silence. A
stage pointed at the wrong dataset form, or a `--dataset` left on a
command that should see every dataset, does not error -- it selects
nothing and reports success.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ARGO = Path(__file__).resolve().parent.parent / "k8s" / "argo"
TEMPLATE = ARGO / "housekeeping-workflow.yaml"
CRON = ARGO / "housekeeping-cronworkflow.yaml"

#: The slugs `datasets.slug` actually holds. `enrich run` matches
#: `WHERE d.slug = :dataset`, and the label form ("Mizzou Missouri
#: State") selects nothing while exiting 0.
SLUGS = {
    "Mizzou-Missouri-State",
    "Penn-State-Lehigh",
    "VT-Community-News",
    "WSU-Washington-State",
}


@pytest.fixture(scope="module")
def template():
    return yaml.safe_load(TEMPLATE.read_text())


@pytest.fixture(scope="module")
def steps(template):
    entry = next(
        t for t in template["spec"]["templates"] if t["name"] == "housekeeping"
    )
    return [s[0] for s in entry["steps"]]


@pytest.fixture(scope="module")
def by_name(template):
    return {t["name"]: t for t in template["spec"]["templates"]}


def test_the_stages_run_in_pipeline_order(steps):
    """A guard first, then `article` -> extracted -> labeled -> enriched.
    Classify before extract would label yesterday's work and leave
    today's, and the run would still report success.

    MAINTENANCE RUNS AHEAD OF THE GUARD, and is listed here rather than
    excused. `reclaim-wire-checks` puts a wire check that never finished
    back in the queue; it owes nothing in `pipeline_rework` -- no review
    rewound it -- so behind the guard it would run only on nights that
    happen to have rework, which is almost none of them. It touches no
    stage and no stage depends on it, so it cannot disturb the order
    below.
    """
    assert [s["name"] for s in steps] == [
        "reclaim-wire-checks",
        "anything-owed",
        # How many extraction workers the night needs, computed from the
        # rework backlog. The extract step fans out over them.
        "rework-workers",
        "extract",
        "classify",
        "enrich",
        # Applying a reviewer's geography is NOT here. It is the template's
        # `onExit` handler, because a sixth step does not run: Argo stops a
        # sequential list at the first failure. See
        # `test_applying_manual_geography_is_an_exit_handler`.
    ]


def test_it_does_no_discovery_or_verification(steps, template):
    """THE DISTINCTION, and it is not "no collection". Extraction is
    collection -- it goes out and fetches -- and housekeeping does it,
    because a record waiting at `article` has a URL already found and
    already verified, and fetching it is the next step of finishing it.

    What housekeeping does not do is look for URLs that are not yet
    known. Discovery walks a publisher's site and verification judges
    what it found; both belong to the dataset crons. A link a reviewer
    restores to `discovered` waits for those, and is not carried here."""
    assert not {"discover-urls", "verify-urls", "discovery", "verification"} & {
        s["name"] for s in steps
    }
    body = TEMPLATE.read_text()
    for collection in ("discover-urls", "verify-urls"):
        assert f"- {collection}" not in body, f"{collection} is a collection stage"


def test_enrichment_takes_the_named_set_not_a_dataset(steps, by_name):
    """`enrich backfill --rework` takes the articles pipeline_rework
    names, whatever dataset they are in. Iterating datasets with
    `enrich run` was the earlier design, and it swept: `run` selects
    every article at `labeled` in the dataset, 85,189 of them, and the
    ceiling would have been spent on records nobody asked about.

    Cost by dataset survives: `article_enrichment.cost_usd` is per
    article and `articles.dataset_id` is populated, so attribution is a
    GROUP BY afterwards and does not need the run to be per dataset."""
    enrich = next(s for s in steps if s["name"] == "enrich")
    assert "withItems" not in enrich
    command = " ".join(by_name["enrich-step"]["container"]["command"])
    assert "backfill" in command and "--rework" in command
    assert "--dataset" not in command


def test_extraction_and_classification_are_not_dataset_scoped(by_name):
    """A rewound record is carried whichever dataset it belongs to.
    `extract` treats `--dataset` as an optional narrowing and `analyze`
    classifies across every dataset when `--dataset-id` is omitted --
    passing either would silently skip three datasets."""
    for stage in ("extraction-step", "classify-step"):
        command = by_name[stage]["container"]["command"]
        assert "--dataset" not in command, f"{stage} is scoped to one dataset"
        assert "--dataset-id" not in command, f"{stage} is scoped to one dataset"


def test_each_stage_runs_the_command_it_claims(by_name):
    assert "extract" in by_name["extraction-step"]["container"]["command"]
    assert "analyze" in by_name["classify-step"]["container"]["command"]
    enrich = by_name["enrich-step"]["container"]["command"]
    assert "backfill" in enrich and "run" not in enrich


def test_enrichment_is_on_because_it_is_targeted(steps):
    """It was off while `enrich run` was the only verb wired, because
    `run` sweeps. `backfill --rework` takes a named set, so the reason to
    keep it off is gone -- and a step that stays off after its reason is
    gone is a step nobody remembers to turn on."""
    enrich = next(s for s in steps if s["name"] == "enrich")
    assert "enrich-enabled" not in enrich.get("when", "")
    assert "anything-owed" in enrich["when"]


def test_enrichment_is_bounded_by_a_ceiling(by_name, template):
    """The only stage that spends money. The set is bounded by
    pipeline_rework; the ceiling bounds the night whatever that set's
    size."""
    env = {
        e["name"]: e.get("value") for e in by_name["enrich-step"]["container"]["env"]
    }
    assert "ENRICHMENT_SPEND_CEILING_USD" in env
    entry = next(
        t for t in template["spec"]["templates"] if t["name"] == "housekeeping"
    )
    params = {p["name"]: p.get("value") for p in entry["inputs"]["parameters"]}
    assert float(params["enrich-ceiling"]) <= 25, "a nightly top-up, not a backfill"


def test_each_stage_gets_the_memory_its_work_needs(by_name):
    """The first run was OOMKilled at 2Gi on extraction.

    The batches here are small, and the memory is not about the batch: a
    single article is what costs it -- parsing one large page -- so
    extraction needs what extraction needs whether it runs 25 or 20,000.
    These are the numbers the pipeline and the processor deployment
    already use in production, rather than smaller ones chosen to match
    the smaller batches.
    """
    floors = {
        "extraction-step": (2, 6),
        "classify-step": (2, 4),
        "enrich-step": (0.5, 1),
    }

    def gigabytes(value):
        if value.endswith("Mi"):
            return int(value[:-2]) / 1024
        return float(value.rstrip("Gi"))

    for stage, (want_request, want_limit) in floors.items():
        resources = by_name[stage]["container"]["resources"]
        assert gigabytes(resources["requests"]["memory"]) >= want_request, stage
        assert gigabytes(resources["limits"]["memory"]) >= want_limit, stage


def test_extraction_asks_for_what_the_pipeline_asks_for(by_name):
    """Read from the pipeline template rather than repeated here, so the
    two cannot drift apart silently -- which is how they started."""
    import yaml

    pipeline = yaml.safe_load((ARGO / "base-pipeline-workflow.yaml").read_text())
    theirs = next(
        t for t in pipeline["spec"]["templates"] if t["name"] == "extraction-step"
    )["container"]["resources"]
    mine = by_name["extraction-step"]["container"]["resources"]
    assert mine["limits"]["memory"] == theirs["limits"]["memory"]
    assert mine["requests"]["memory"] == theirs["requests"]["memory"]


def test_enrichment_is_not_retried(by_name):
    """A retried batch is a batch paid for twice. `enrich run` resumes by
    status, so tomorrow's run continues from wherever this one stopped."""
    assert "retryStrategy" not in by_name["enrich-step"]


def test_the_free_stages_are_retried(by_name):
    """They cost nothing and a transient failure should not park a
    record for a day."""
    for stage in ("extraction-step", "classify-step"):
        assert by_name[stage].get("retryStrategy"), stage


def test_the_nightly_slot_sits_between_the_other_two_jobs():
    """02:00 applies reviewed geography; 07:00 publishes to BigQuery. The
    nightly slot has to sit between them.

    It is the FIRST slot that carries this: the job runs several times a
    day so a queue bigger than one window drains the same day, and the
    later slots are retries that happen well clear of both. Asserting the
    whole hour field is a single number said "runs once", which was never
    the requirement -- the requirement is that the night's run lands in
    that gap. `test_no_run_spans_the_bigquery_sync` covers the rest."""
    cron = yaml.safe_load(CRON.read_text())
    minute, hours = cron["spec"]["schedule"].split()[:2]
    assert minute.isdigit(), cron["spec"]["schedule"]
    first = hours.split(",")[0]
    assert first.isdigit(), cron["spec"]["schedule"]
    assert 2 < int(first) < 7, f"the nightly slot is at {first}:{minute} UTC"


def test_a_run_still_going_is_not_replaced():
    """`Replace` would start a second spend ceiling rather than continue
    the first."""
    cron = yaml.safe_load(CRON.read_text())
    assert cron["spec"]["concurrencyPolicy"] == "Forbid"


def test_the_cron_calls_the_template_this_file_defines(template):
    cron = yaml.safe_load(CRON.read_text())
    wrapper = cron["spec"]["workflowSpec"]["templates"][0]
    ref = wrapper["steps"][0][0]["templateRef"]
    assert ref["name"] == template["metadata"]["name"]
    assert ref["template"] == "housekeeping"


def test_applying_manual_geography_is_the_runs_exit_handler():
    """IT CANNOT BE A STEP, and it was one.

    Argo stops a sequential `steps:` list at the first failure, so a step
    placed after `enrich` does not run when enrichment fails -- a model
    timeout, a ceiling hit, a terminated run. All four housekeeping runs on
    2026-09-13 ended with `enrich` failed. A sixth step would have run in
    none of them, and the contributions it exists to move would have sat
    exactly as they did before it was added.

    A step gated on `anything-owed` fails the same way for a different
    reason: the count is blind to a geography decision, which writes no
    `pipeline_rework` row, so a quiet night still has contributions to
    move. A run-level exit handler answers both, and still runs after
    enrichment -- which the ordering requires, because `persist_outcome`
    DELETEs an article's `article_geoids` rows before writing its own.
    """
    spec = yaml.safe_load(CRON.read_text())["spec"]["workflowSpec"]
    assert spec.get("onExit") == "apply-manual-geography"
    handler = next(t for t in spec["templates"] if t["name"] == spec["onExit"])
    ref = handler["steps"][0][0]["templateRef"]
    assert ref["name"] == "housekeeping-template"
    assert ref["template"] == "apply-manual-step"


def test_the_exit_handler_is_not_on_the_workflow_template(template):
    """WHERE IT WOULD LINT CLEAN AND NEVER RUN.

    The wrapper reaches `housekeeping` through a `templateRef`, and a
    WorkflowTemplate's spec-level fields are not inherited through one. So
    an `onExit` in housekeeping-workflow.yaml is dead config -- `argo lint`
    accepts it at spec level and rejects it per template, and neither
    fires. The handler belongs to the run, so it is declared on the
    cronworkflow's `workflowSpec`."""
    assert (
        "onExit" not in template["spec"]
    ), "a WorkflowTemplate spec.onExit never fires through a templateRef"
    for t in template["spec"]["templates"]:
        assert "onExit" not in t, f"{t['name']} declares an onExit that cannot run"


def test_argo_itself_accepts_these_manifests():
    """THE AUTHORITY ON THE SCHEMA IS ARGO, NOT US.

    Every other test here parses the YAML and asserts shape, which tests
    what we wrote and not what Argo will accept. `onExit` on a template
    passed all of them and is not a field: `argo lint` says
    `strict decoding error: unknown field "spec.templates[0].onExit"`.
    Nothing in CI would have caught it -- Validate K8s Workflows checks
    YAML syntax and our own SQL/flag rules, and never runs `argo lint`.

    Skipped, loudly, when the binary is absent: a skip is not a pass, and
    CI does not install argo today.

    WHAT THIS FILE STILL DOES NOT PROVE: that Argo runs the exit handler.
    Shape and schema are all a parsed manifest can tell you; whether a
    handler fires on a failed or skipped run is runtime behaviour, and no
    unit test here reaches it. It was measured instead --
    k8s/argo/probes/onexit-semantics-probe.yaml, two busybox pods, results
    recorded in the cronworkflow beside the `onExit` it justifies.
    """
    argo = shutil.which("argo")
    if argo is None:
        pytest.skip("argo CLI not installed; the schema is unvalidated here")
    result = subprocess.run(
        [argo, "lint", "--offline", str(TEMPLATE), str(CRON)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
