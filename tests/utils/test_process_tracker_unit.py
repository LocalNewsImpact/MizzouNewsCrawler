import types

import pytest

from src.utils import process_tracker as pt


def test_format_duration_variations():
    assert pt.format_duration(12.34) == "12.3s"
    assert pt.format_duration(125) == "2m 5s"
    assert pt.format_duration(7205) == "2h 0m"


def test_format_progress_with_and_without_total():
    process = types.SimpleNamespace(
        progress_total=20,
        progress_current=5,
        progress_percentage=25.0,
    )
    detailed = pt.format_progress(process)  # type: ignore[arg-type]
    assert detailed == "5/20 (25.0%)"

    process_no_total = types.SimpleNamespace(
        progress_total=None,
        progress_current=3,
        progress_percentage=None,
    )
    minimal = pt.format_progress(process_no_total)  # type: ignore[arg-type]
    assert minimal == "3 items"


def test_process_context_tracks_success(monkeypatch):
    calls = {"complete": [], "register": None}

    class Tracker:
        def register_process(self, *args, **kwargs):
            process = types.SimpleNamespace(id="proc-1")
            calls["register"] = process
            return process

        def complete_process(self, process_id, status, error_message=None):
            calls["complete"].append((process_id, status, error_message))

    monkeypatch.setattr(pt, "get_tracker", lambda: Tracker())

    with pt.ProcessContext("type", "command"):
        pass

    assert calls["complete"] == [("proc-1", "completed", None)]
    assert calls["register"].id == "proc-1"


def test_process_context_tracks_failure(monkeypatch):
    calls = {"complete": []}

    class Tracker:
        def register_process(self, *args, **kwargs):
            return types.SimpleNamespace(id="proc-2")

        def complete_process(self, process_id, status, error_message=None):
            calls["complete"].append((process_id, status, error_message))

    monkeypatch.setattr(pt, "get_tracker", lambda: Tracker())

    with pytest.raises(RuntimeError):
        with pt.ProcessContext("type", "command"):
            raise RuntimeError("boom")

    assert calls["complete"][0][1] == "failed"
    assert "boom" in calls["complete"][0][2]
