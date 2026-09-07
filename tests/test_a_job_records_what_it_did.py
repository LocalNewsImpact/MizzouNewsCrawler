"""A job row says a run happened and nothing about what it did.

`jobs` holds 769 rows going back to November, each with the dataset in
`params`, a start, a finish and an exit status -- and
`records_processed`, `records_created` and `errors_count` all zero.

The write path was complete. `_update_job_record` fills all four
counters when it is handed `metrics`, and the tracker has been holding
them the whole time on `active_operations[id]["metrics"]`, put there by
`update_progress`. Neither `complete_operation` nor `fail_operation`
read them back out, so the branch that writes them could never run.

That is the same defect as everywhere else in this pipeline: a stage
that can act but cannot account for itself.
"""

from unittest.mock import patch

import pytest

from src.utils.telemetry import OperationMetrics, OperationStatus, OperationTracker


@pytest.fixture
def tracker():
    return OperationTracker()


def _captured(tracker, op_id, finish):
    """The kwargs `_update_job_record` was called with."""
    with (
        patch.object(tracker, "_update_job_record") as job_record,
        patch.object(tracker, "_send_event"),
    ):
        finish(op_id)
    assert job_record.called, "the job record must be written either way"
    return job_record.call_args.kwargs


def test_a_completed_job_records_its_counts(tracker):
    op = "op-1"
    tracker.active_operations[op] = {
        "metrics": OperationMetrics(total_items=10, processed_items=8, failed_items=2)
    }

    kwargs = _captured(tracker, op, lambda i: tracker.complete_operation(i))

    assert kwargs["metrics"].processed_items == 8
    assert kwargs["metrics"].failed_items == 2


def test_a_failed_job_records_how_far_it_got(tracker):
    """More important than the success case: the first question about a
    failure is how much it managed before it stopped."""
    op = "op-2"
    tracker.active_operations[op] = {
        "metrics": OperationMetrics(total_items=100, processed_items=37, failed_items=1)
    }

    kwargs = _captured(
        tracker, op, lambda i: tracker.fail_operation(i, "proxy refused")
    )

    assert kwargs["metrics"].processed_items == 37
    assert kwargs["error_details"]["message"] == "proxy refused"


def test_an_operation_that_reported_nothing_still_finishes(tracker):
    """Not every run reports progress. A missing metric is None, not a
    crash, and the job still gets its exit status."""
    tracker.active_operations["op-3"] = {}

    kwargs = _captured(tracker, "op-3", lambda i: tracker.complete_operation(i))

    assert kwargs["metrics"] is None


def test_an_unknown_operation_does_not_raise(tracker):
    """Completion can arrive for an operation this process never
    started -- a restart mid-run. It must not take the worker down."""
    kwargs = _captured(
        tracker, "never-started", lambda i: tracker.complete_operation(i)
    )
    assert kwargs["metrics"] is None


def test_the_counters_come_from_the_metrics_the_run_reported():
    """The mapping `_update_job_record` applies, pinned: created is
    processed minus failed, and errors is failed."""
    import inspect

    source = inspect.getsource(OperationTracker._update_job_record)
    assert "records_processed = ?" in source
    assert "records_created = ?" in source
    assert "errors_count = ?" in source
    assert "metrics_obj.processed_items" in source
