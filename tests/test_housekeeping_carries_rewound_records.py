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
    """A record moves `article` -> extracted -> labeled -> enriched.
    Classify before extract would label yesterday's work and leave
    today's, and the run would still report success."""
    assert [s["name"] for s in steps] == ["extract", "classify", "enrich"]


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


def test_enrichment_names_every_dataset_by_its_slug(steps):
    """`enrich run` requires `--dataset` and matches `datasets.slug`.
    Naming the datasets here rather than relaxing the flag gives each its
    own limit and its own ceiling, so Mizzou's 83,048 waiting articles
    cannot spend the budget that would otherwise carry VT's 1,017."""
    enrich = next(s for s in steps if s["name"] == "enrich")
    assert set(enrich["withItems"]) == SLUGS


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
    assert enrich[-6:-4] == ["enrich", "run"] or "run" in enrich


def test_enrichment_is_off_until_it_is_targeted(steps, template):
    """`enrich run` selects ANY article at `labeled` in the dataset, so
    enabling it sweeps the ordinary backlog rather than carrying the
    records a reviewer rewound.

    Measured: 3,607 articles carry a disposition and only 97 of them sit
    at `labeled` -- 72 discovery-disposed, 25 extraction-disposed --
    while a swept run enriches 800 a day, nearly all of them in datasets
    with no dispositions at all. Lehigh and WSU have none whatsoever.

    The step stays wired and bounded, and off, until it points at the set
    the reconciler marks."""
    enrich = next(s for s in steps if s["name"] == "enrich")
    assert "when" in enrich, "the enrich step sweeps the backlog unguarded"

    params = {
        p["name"]: p.get("value")
        for p in next(
            t for t in template["spec"]["templates"] if t["name"] == "housekeeping"
        )["inputs"]["parameters"]
    }
    assert params["enrich-enabled"] == "false"


def test_enrichment_is_bounded_by_a_ceiling_and_a_limit(by_name, steps):
    """The only stage that spends money. Unbounded it would work through
    a backlog this workflow has no business touching."""
    enrich_step = by_name["enrich-step"]
    env = {e["name"]: e.get("value") for e in enrich_step["container"]["env"]}
    assert "ENRICHMENT_SPEND_CEILING_USD" in env
    assert "--limit" in enrich_step["container"]["command"]

    entry_inputs = {
        p["name"]: p.get("value")
        for p in next(
            t
            for t in yaml.safe_load(TEMPLATE.read_text())["spec"]["templates"]
            if t["name"] == "housekeeping"
        )["inputs"]["parameters"]
    }
    assert (
        int(entry_inputs["enrich-limit"]) <= 500
    ), "a housekeeping run, not a backfill"
    assert float(entry_inputs["enrich-ceiling"]) <= 10


def test_enrichment_is_not_retried(by_name):
    """A retried batch is a batch paid for twice. `enrich run` resumes by
    status, so tomorrow's run continues from wherever this one stopped."""
    assert "retryStrategy" not in by_name["enrich-step"]


def test_the_free_stages_are_retried(by_name):
    """They cost nothing and a transient failure should not park a
    record for a day."""
    for stage in ("extraction-step", "classify-step"):
        assert by_name[stage].get("retryStrategy"), stage


def test_it_runs_before_the_bigquery_sync_and_after_the_other_housekeeping():
    """02:00 applies reviewed geography; 07:00 publishes to BigQuery.
    This has to sit between them."""
    cron = yaml.safe_load(CRON.read_text())
    minute, hour = cron["spec"]["schedule"].split()[:2]
    assert minute.isdigit() and hour.isdigit(), cron["spec"]["schedule"]
    assert 2 < int(hour) < 7, f"scheduled at {hour}:{minute} UTC"


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
