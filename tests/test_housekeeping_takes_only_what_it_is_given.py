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


#: Steps that run whatever the night holds, and why each one has to.
#:
#: The rule this test protects is that no STAGE runs on an empty night.
#: A step that is not a stage, and whose work the rework count cannot
#: see, is a different thing -- and naming them here is what keeps the
#: exemption a decision rather than a hole: anything not on this list is
#: still required to be gated.
UNGATED_BY_DESIGN = {
    # A wire check stranded at `processing` or `error` owes nothing in
    # `pipeline_rework` -- no review rewound it, so no row names it.
    # Behind the gate it would be reclaimed only on nights that happen to
    # have rework, which is almost none of them, and the four found in
    # production had been stuck between six and ten months.
    "reclaim-wire-checks",
    # An ingested URL that nothing has checked owes nothing to rework either.
    # It records a url_verifications row per link and never writes a status,
    # so it cannot start a stage's work; and gated, a link ingested on a quiet
    # night would go unchecked until a night that happened to have rework.
    "check-ingested",
    # The byline queue is a count of the corpus as it is now, not work a
    # review decision rewound. Behind the gate it would refresh only on nights
    # that happen to have rework.
    "refresh-byline-queue",
}


def test_a_run_with_nothing_owed_stops_before_starting_a_stage(stages):
    """Every stage is gated on what is owed. An empty night costs a few
    seconds, not three pods."""
    entry = stages["housekeeping"]
    names = [s[0]["name"] for s in entry["steps"]]
    # The guard runs before any stage. Maintenance may precede it; a
    # stage may not.
    assert names.index("anything-owed") == len(UNGATED_BY_DESIGN)
    # Every later step, the worker-count step included: computing how many
    # workers a night needs is itself work, and an empty night should not
    # start a pod to be told there is nothing to do.
    #
    # Applying a reviewer's geography needs to run ungated -- the count
    # cannot see its work -- and it does, as the run's exit handler on the
    # cronworkflow rather than as a step. So this rule needs no exemption.
    for step in entry["steps"][names.index("anything-owed") + 1 :]:
        assert "anything-owed" in step[0].get("when", ""), step[0]["name"]


def test_nothing_is_ungated_without_being_named(stages):
    """The exemption list is the point. A step added ahead of the guard
    without appearing here is a stage that silently stopped being gated,
    which is how an empty night starts costing three pods again."""
    entry = stages["housekeeping"]
    names = [s[0]["name"] for s in entry["steps"]]
    before_the_guard = set(names[: names.index("anything-owed")])
    assert before_the_guard == UNGATED_BY_DESIGN


def _cron():
    return yaml.safe_load(
        (ROOT / "k8s/argo/housekeeping-cronworkflow.yaml").read_text()
    )


def test_no_run_spans_the_bigquery_sync():
    """EVERY slot, not just the first.

    The rule is that the 07:00 UTC sync never reads while a run is
    writing. This used to read the single scheduled hour and check
    `hour + 3 <= 7`, which only says anything about a job that runs once
    before the sync -- add a slot at 09:00 and that formula either throws
    on the hour list or declares a perfectly safe window unsafe.

    What has to hold is that no slot's three-hour window contains 07:00.
    """
    cron = _cron()
    deadline = cron["spec"]["workflowSpec"]["activeDeadlineSeconds"]
    hours = [int(h) for h in cron["spec"]["schedule"].split()[1].split(",")]
    span = deadline / 3600
    for hour in hours:
        # Half-open: a run starting at 04:00 occupies 04:00-07:00 and has
        # released the deadline by the time the sync reads.
        running = {(hour + o) % 24 for o in range(int(span))}
        assert 7 not in running, f"the {hour:02d}:00 slot is still going at 07:00"


def test_the_deadline_leaves_room_before_the_sync():
    """The first slot is the nightly one and still has to land before the
    sync with the whole window used."""
    cron = _cron()
    deadline = cron["spec"]["workflowSpec"]["activeDeadlineSeconds"]
    first = int(cron["spec"]["schedule"].split()[1].split(",")[0])
    assert first + deadline / 3600 <= 7


def test_the_schedule_runs_and_says_so_in_the_manifest():
    """DAILY, and declared here rather than patched on the cluster.

    This job processes what a review-queue disposition presents and nothing
    else. It is not coupled to the dataset crons -- those are suspended
    because they go looking for URLs, and this one does no discovery and no
    verification -- so suspending it alongside them conflated two unrelated
    decisions, and a disposition made in a queue reached nothing.

    The state belongs in the manifest either way: a cluster patch is
    invisible in the repository and undone by the next apply, and an apply
    ran the same night this was resumed.

    It was held suspended until the sweep that caused it was fixed -- a run
    took 4,802 links when the dispositions accounted for 45. That is fixed
    at the source, and `test_no_stage_runs_a_bare_sweeping_command` and
    `test_a_run_with_nothing_owed_stops_before_starting_a_stage` are what
    keep it fixed. This test does not re-litigate that; it holds the
    schedule declared and running."""
    cron = _cron()
    assert "suspend" in cron["spec"], "declare the state; do not patch the cluster"
    assert cron["spec"]["suspend"] is False
    hours = [int(h) for h in cron["spec"]["schedule"].split()[1].split(",")]
    assert hours[0] == 3, "the nightly slot still runs after the 02:00 housekeeping"


def test_it_runs_more_than_once_a_day():
    """A QUEUE BIGGER THAN ONE WINDOW HAS TO DRAIN THE SAME DAY.

    On 2026-09-14 a review session queued 235 records; the run was killed
    by the three-hour deadline eight short, and with a single daily slot
    those eight had no further chance for 24 hours. Nothing retried in
    between because nothing was scheduled in between.

    `Forbid` is what keeps this honest: a slot arriving while the previous
    run is still going is skipped, so these are retries, not six
    concurrent runs."""
    cron = _cron()
    hours = [int(h) for h in cron["spec"]["schedule"].split()[1].split(",")]
    assert len(hours) > 1, "one slot a day cannot clear more than one window"
    assert cron["spec"]["concurrencyPolicy"] == "Forbid"


def test_a_quiet_slot_costs_nothing(stages):
    """The extra slots are only affordable because an empty one stops
    before starting a stage. That guard already exists -- this ties it to
    the schedule, so the slots and the guard cannot drift apart."""
    entry = stages["housekeeping"]
    steps = [s for group in entry["steps"] for s in group]
    owed = next(s for s in steps if s["name"] == "anything-owed")
    assert steps.index(owed) < min(
        steps.index(s) for s in steps if s["name"] in {"extract", "classify", "enrich"}
    ), "the owed check must run before any stage"


def test_no_stage_runs_a_bare_sweeping_command(stages):
    """The specific commands that take everything: `extract` with no ids,
    `analyze` with no ids, `enrich run` at all (its targeted form is
    `enrich backfill --ids-file`).

    `enrich apply-manual` is not one of them. It sweeps nothing: its input
    is `article_places_manual`, a table only a reviewer writes to, so the
    set is already exactly what somebody asked for. There is no `--rework`
    to give it and no status it selects on."""
    for name, stage in stages.items():
        container = stage.get("container")
        if not container:
            continue
        command = " ".join(container["command"])
        if "apply-manual" in command:
            assert " run " not in f" {command} "
            continue
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
    """The settle existed, was tested on its own, and was never
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
        patch("src.cli.commands.extraction._settle_rework", return_value=1) as settle,
    ):
        _one_link_batch(env, "link-1")
        assert handle_extraction_command(args) == 0
        # Twice: once before the batch, where a run whose links were all
        # fetched earlier still closes their rows, and once after the batch
        # that has just fetched some.
        assert settle.call_count >= 1


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
        patch("src.cli.commands.extraction._settle_rework") as settle,
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


def test_no_stage_queues_another_one():
    """A record is carried by the join of its flag and its status, not by a
    stage writing a row for the next one.

    The first version had extraction write a `classify` row when a fetch
    produced an article. It fired on the article's status at the end of the
    batch -- before cleaning had run -- so it matched nothing: production
    logged "27 fetches settled, 0 articles queued for classification" and
    four fresh articles sat at `labeled` with nothing asking for their
    enrichment."""
    for path in (
        ROOT / "src/pipeline/rework.py",
        EXTRACTION,
        CLASSIFIER,
        ROOT / "src/enrichment/repository.py",
    ):
        source = path.read_text()
        assert "INSERT INTO pipeline_rework" not in source, path.name


def test_every_stage_reads_the_same_set():
    """One definition. A copy per stage is a copy that drifts, and the set
    is the only thing that makes a housekeeping run different from an
    ordinary one."""
    for path in (EXTRACTION, CLASSIFIER, ROOT / "src/enrichment/repository.py"):
        assert "from src.pipeline.rework import" in path.read_text(), path.name


# --- the same workers and the same queue, a narrower set -------------------------


def test_extraction_runs_parallel_workers(stages):
    """One worker at a time was going to miss the window: a page costs two
    to four minutes when the first fetch comes back unusable and Selenium
    retries, so 97 links serially is hours. The pipeline template already
    fans extraction out; this does the same."""
    entry = stages["housekeeping"]
    extract = next(
        step for group in entry["steps"] for step in group if step["name"] == "extract"
    )
    assert extract.get("withParam"), "extraction does not fan out"
    assert "rework-workers" in extract["withParam"]


def test_the_worker_count_comes_from_the_rework_backlog(stages):
    """Not from the extraction backlog. A housekeeping run's size is the
    number of records a decision rewound -- tens -- and scaling off 4,802
    would start workers with nothing to do."""
    body = (ROOT / "k8s/argo/housekeeping-workflow.yaml").read_text()
    count = body.split("name: rework-worker-count")[1].split("- name:")[0]
    assert "FROM pipeline_rework" in count
    assert "done_at IS NULL" in count
    assert "cl.status = 'article'" in count, "and ready to fetch, not merely flagged"


def _worker_count():
    """The shipped sizing rule, as a callable.

    Lifted from the manifest rather than reimplemented: a copy in the test
    would only prove the copy right, and this rule is arithmetic whose
    edges are the whole point.
    """
    body = yaml.safe_load(WORKFLOW.read_text())
    src = next(
        t for t in body["spec"]["templates"] if t["name"] == "rework-worker-count"
    )["script"]["source"]
    line = next(ln for ln in src.splitlines() if ln.strip().startswith("workers ="))
    expr = line.split("=", 1)[1].strip()
    return lambda owed, hosts: eval(
        expr, {}, {"owed": owed, "hosts": hosts}
    )  # noqa: S307


def test_the_worker_count_is_bounded_by_domain_spread():
    """THE REAL CONSTRAINT, AND IT USED TO BE A GUESSED CONSTANT.

    The queue hands out at most three articles per domain per request, so
    a worker needs roughly three domains to stay busy. That was expressed
    as a flat cap of 4, which is right only for the batch shape it was
    written against.

    A concentrated batch must not fan out however many records it holds:
    234 links across three publishers is one worker's work, and four
    workers would queue up behind one site."""
    workers = _worker_count()
    assert workers(234, 3) == 1
    assert workers(234, 6) == 2


def test_a_wide_batch_is_not_throttled_to_the_old_cap():
    """THE REGRESSION THIS FIXES. On 2026-09-14 a review session queued 235
    records spanning 48 domains. The rule asked for 10 workers, the flat
    cap gave it 4, and the three-hour deadline killed the run having
    finished 227 -- throttled to 40% of its own computed parallelism and
    missing by eight records, with nothing contending for domains."""
    workers = _worker_count()
    assert workers(235, 48) > 4


def test_the_worker_count_still_has_a_ceiling():
    """Proxy and Selenium capacity are shared with everything else and are
    not measured here, so the rule is bounded however wide the batch."""
    workers = _worker_count()
    assert workers(10_000, 5_000) <= 8


def test_a_quiet_queue_starts_one_worker_not_none():
    """`withParam` over an empty list starts no pods and the step reports
    success, which would read as "the queue is clear" on a night it is
    not. The owed check is what stops an empty run, not a zero here."""
    workers = _worker_count()
    assert workers(0, 0) == 1
    assert workers(1, 1) == 1


def test_the_workers_pull_from_the_work_queue(stages):
    """The queue hands each worker its own domains, so four workers do not
    queue up behind one publisher. It is the same queue the pipeline's
    workers use."""
    entry = stages["extraction-step"]
    env = {e["name"]: e.get("value") for e in entry["container"]["env"]}
    assert env.get("USE_WORK_QUEUE") == "true"
    assert "work-queue" in (env.get("WORK_QUEUE_URL") or "")


def test_the_queue_serves_only_rework_records_when_asked():
    """The one difference between a housekeeping worker and a pipeline
    worker. Without it a worker draws from the whole extraction backlog,
    which is the sweep this design exists to prevent."""
    queue = (ROOT / "src/services/work_queue.py").read_text()
    assert "REWORK_ONLY" in queue
    assert "FROM pipeline_rework r" in queue
    assert "rework: bool" in queue
    crawler = EXTRACTION.read_text()
    assert '"rework": rework' in crawler, "the request carries it"


def test_the_queue_filters_both_of_its_queries():
    """Filtering only the claim query would hand a worker a domain whose
    links are all backlog: it comes back empty while the rework links sit
    behind a domain nobody was assigned."""
    queue = (ROOT / "src/services/work_queue.py").read_text()
    assert queue.count("REWORK_ONLY") >= 3, "defined once, used in both queries"


# --- a contribution reaches the export ---------------------------------------
#
# `enrich apply-manual` puts geography a person entered into
# `article_geoids`, which is what BigQuery's "Sync Article Geoids" reads,
# unfiltered, at 07:00 UTC. docs/MANUAL_GEOGRAPHY.md says it must run
# daily before then. It was wired into nothing, so 56 contributions across
# two days of review sat in `article_places_manual` and reached no
# consumer.


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _templates():
    return {t["name"]: t for t in _workflow()["spec"]["templates"]}


def test_housekeeping_applies_manual_geography_on_exit():
    """As the exit handler, not a step: Argo stops a sequential `steps:`
    list at the first failure, and all four runs on 2026-09-13 ended with
    `enrich` failed."""
    cron = yaml.safe_load(
        (ROOT / "k8s/argo/housekeeping-cronworkflow.yaml").read_text()
    )
    assert cron["spec"]["workflowSpec"].get("onExit") == "apply-manual-geography"


def test_it_runs_whether_or_not_anything_is_owed():
    """A geography decision writes no `pipeline_rework` row -- the
    reconciler reads the discovery and extraction queues and not that one
    -- so `anything-owed` is blind to it. Gated on that count, a night
    with no rework would carry no contributions either, which is the
    failure this step exists to end. An exit handler cannot be gated,
    which is part of why it is the right shape here."""
    assert "when" not in _templates()["apply-manual-step"]


def test_it_runs_even_when_enrichment_fails():
    """THE DEFECT THIS REPLACED, asserted directly. A sixth step is
    unreachable on a failed enrichment; an exit handler is not. If anyone
    moves it back into `steps`, this fails."""
    names = [s[0]["name"] for s in _templates()["housekeeping"]["steps"]]
    assert "apply-manual-geography" not in names
    assert names[-1] == "enrich"


def test_it_makes_no_model_calls():
    """No spend ceiling and no OpenRouter key. It reads
    `article_places_manual` and writes `article_geoids`; a key it does not
    need is a key that can be wrong, and a missing one restarted the
    enrich container 278 times."""
    container = _templates()["apply-manual-step"]["container"]
    names = {e["name"] for e in container["env"]}
    assert "OPENROUTER_API_KEY" not in names
    assert "ENRICHMENT_SPEND_CEILING_USD" not in names


def test_it_asks_for_no_parameters_it_does_not_declare():
    """`enrich-step` once read `{{workflow.parameters.enrich-ceiling}}`,
    which nothing declared, and spent against whatever an unresolved
    template string becomes. This template declares no inputs, so it must
    reference none."""
    template = _templates()["apply-manual-step"]
    assert template.get("inputs") is None
    assert "inputs.parameters" not in yaml.dump(template)


def test_it_runs_the_command_the_docs_name():
    command = _templates()["apply-manual-step"]["container"]["command"]
    assert command[-2:] == ["enrich", "apply-manual"]


def test_the_enrich_step_is_untouched():
    """The new step is modelled on `enrich-step` and must not have changed
    it: enrichment still takes the rework set and still spends against a
    declared ceiling."""
    container = _templates()["enrich-step"]["container"]
    assert container["command"][-2:] == ["backfill", "--rework"]
    assert "ENRICHMENT_SPEND_CEILING_USD" in {e["name"] for e in container["env"]}
