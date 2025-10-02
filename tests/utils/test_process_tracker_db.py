from datetime import datetime, timedelta

import pytest

from src.models import BackgroundProcess
from src.utils import process_tracker as pt


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'process_tracker.sqlite'}"
    tracker = pt.ProcessTracker(db_url)
    monkeypatch.setattr(pt, "_tracker", tracker)
    try:
        yield tracker
    finally:
        tracker.db.close()
        monkeypatch.setattr(pt, "_tracker", None)


def test_register_and_get_process(tracker):
    process = tracker.register_process(
        process_type="ingest",
        command="python ingest.py",
        pid=456,
        dataset_id="dataset-123",
        source_id="source-789",
        metadata={"batch": 7},
    )

    assert process.status == "started"
    assert process.pid == 456
    assert process.dataset_id == "dataset-123"

    fetched = tracker.get_process_by_id(process.id)
    assert fetched is not None
    assert fetched.id == process.id
    assert fetched.process_metadata == {"batch": 7}


def test_update_progress_and_completion(tracker):
    process = tracker.register_process("cleanup", "python cleanup.py")

    tracker.update_progress(
        process.id,
        current=5,
        total=10,
        message="halfway",
        status="running",
    )

    updated = tracker.get_process_by_id(process.id)
    assert updated.progress_current == 5
    assert updated.progress_total == 10
    assert updated.progress_message == "halfway"
    assert updated.status == "running"

    tracker.complete_process(
        process.id,
        status="completed",
        result_summary={"rows": 100},
    )

    completed = tracker.get_process_by_id(process.id)
    assert completed.status == "completed"
    assert completed.result_summary == {"rows": 100}
    assert completed.completed_at is not None


def test_active_queries_and_cleanup(tracker):
    active = tracker.register_process("extract", "python extract.py")

    inactive = tracker.register_process(
        "extract",
        "python extract.py --batch=old",
    )
    tracker.complete_process(inactive.id, status="completed")

    stale = tracker.register_process(
        "extract",
        "python extract.py --stale",
    )
    tracker.complete_process(stale.id, status="completed")
    with tracker.Session() as session:
        record = session.get(BackgroundProcess, stale.id)
        record.completed_at = datetime.utcnow() - timedelta(hours=48)
        session.commit()

    actives = tracker.get_active_processes()
    assert {p.id for p in actives} == {active.id}

    deleted = tracker.cleanup_stale_processes(max_age_hours=24)
    assert deleted == 1
    remaining = tracker.get_processes_by_type("extract")
    assert stale.id not in {p.id for p in remaining}
    assert inactive.id in {p.id for p in remaining}


def test_get_tracker_returns_singleton(tracker):
    first = pt.get_tracker()
    second = pt.get_tracker()
    assert first is second
    assert first.db.database_url.startswith("sqlite:///")
