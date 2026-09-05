"""A suspended crawler is not a production failure.

`production-smoke-tests.yml` asks Kubernetes whether the crawler CronJob
is suspended and passes the answer to the suite as
COLLECTION_SUSPENDED. The suite has a fixture, `active_collection`, that
skips on it.

One test requested that fixture. Ten did not. So on 2026-09-05, with the
CronJob suspended and the workflow reporting it correctly, the run was
red with twelve failures -- nine of them saying only that nothing had
run, which was true and was the point. A suite that is red for a known
reason teaches everyone to ignore it, including on the day it goes red
for a real one.

This reads the smoke suite's source. A test that asks whether something
happened inside a window has to request the fixture; a test that asks
what the database looks like must not, or a suspension would hide a real
fault.
"""

import ast
import re
from pathlib import Path

import pytest

SMOKE = Path(__file__).resolve().parent / "e2e/test_production_smoke.py"
WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github/workflows/production-smoke-tests.yml"
)

# A query window: `NOW() - INTERVAL '24 hours'` and friends.
WINDOW = re.compile(r"NOW\(\)\s*-\s*INTERVAL", re.IGNORECASE)

# Tests that read a window but assert something about the rows rather than
# about their arrival, so they stay meaningful with collection stopped.
# Each is a real finding when it fails, not a schedule artefact.
WINDOWED_BUT_NOT_ABOUT_FRESHNESS = {
    # Reads a window to count rows, then asserts the connection is
    # configured -- a statement timeout of zero is true whether or not
    # anything is running.
    "test_database_connection_resilience",
    "test_transaction_rollback_on_extraction_errors",
    "test_extraction_failures_are_logged_and_retried",
    "test_extraction_retry_mechanism_works",
    "test_no_duplicate_extractions",
    "test_data_lineage_timestamps_progression",
    "test_transactionality_prevents_partial_states",
    "test_cascade_and_data_lineage",
    "test_duplicate_article_prevention_via_unique_constraint",
    "test_section_url_handling_in_cleaning",
    "test_entity_extraction_gazetteer_loading",
    "test_model_versioning_and_fallback",
    "test_entity_confidence_and_validation",
    "test_extraction_and_labeling_pipeline_completeness",
    "test_extraction_throughput",
    "test_hash_columns_handle_large_values",
    "test_no_orphaned_articles",
    "test_content_quality_checks",
    "test_discovery_verification_extraction_flow",
    "test_section_urls_are_extracted_and_stored",
    "test_section_urls_used_in_discovery",
    "test_article_urls_discovered_from_sections",
}


def _tests():
    """Every test function in the smoke suite, with its source."""
    tree = ast.parse(SMOKE.read_text())
    lines = SMOKE.read_text().splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            source = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            args = [a.arg for a in node.args.args]
            yield node.name, source, args


def _asks_whether_work_happened(name, source):
    """A window, and an assertion that something is inside it."""
    if not WINDOW.search(source):
        return False
    if name in WINDOWED_BUT_NOT_ABOUT_FRESHNESS:
        return False
    return True


@pytest.mark.parametrize(
    "name",
    sorted(
        name
        for name, source, _ in _tests()
        if _asks_whether_work_happened(name, source)
    ),
)
def test_a_freshness_check_skips_when_collection_is_suspended(name):
    args = next(args for n, _, args in _tests() if n == name)
    assert "active_collection" in args, (
        f"{name} asserts that work happened in a time window and does not "
        "request active_collection, so it fails for the suspension rather "
        "than for a fault"
    )


def test_the_fixture_exists_and_reads_the_workflows_answer():
    source = SMOKE.read_text()
    assert "def active_collection()" in source
    assert 'os.getenv("COLLECTION_SUSPENDED"' in source


def test_the_workflow_asks_kubernetes_and_passes_the_answer():
    """The fixture is inert unless something sets the variable."""
    workflow = WORKFLOW.read_text()
    assert "kubectl get cronjob mizzou-crawler" in workflow
    assert "{.spec.suspend}" in workflow
    assert "COLLECTION_SUSPENDED=$COLLECTION_SUSPENDED" in workflow


def test_the_checks_that_describe_the_database_still_run():
    """These fail for a reason a suspension does not explain -- an active
    source missing its city, a statement timeout of zero, articles whose
    status and labels disagree. Putting them behind the fixture would hide
    a real fault for as long as the crons are off."""
    for name in (
        "test_source_metadata_complete",
        "test_database_connection_resilience",
        "test_transaction_rollback_on_extraction_errors",
    ):
        args = next(args for n, _, args in _tests() if n == name)
        assert "active_collection" not in args, f"{name} would be skipped"
