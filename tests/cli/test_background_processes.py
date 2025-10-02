import sys
import types
from datetime import datetime

import pytest

from src.cli.commands import background_processes as bp


@pytest.fixture
def install_background_env(monkeypatch):
    """Stub DatabaseManager and BackgroundProcess model for CLI tests."""

    class StatusAttribute:
        def __init__(self):
            self.values = None

        def in_(self, values):
            self.values = tuple(values)
            return ("status", self.values)

    class StartedAtAttribute:
        def desc(self):
            return ("started_at", "desc")

        def asc(self):
            return ("started_at", "asc")

    class BackgroundProcessModelStub:
        status = StatusAttribute()
        started_at = StartedAtAttribute()

    stub_models_module = types.SimpleNamespace(
        BackgroundProcess=BackgroundProcessModelStub
    )
    monkeypatch.setitem(sys.modules, "src.models", stub_models_module)

    class SessionStub:
        def __init__(self, items):
            self._items = list(items)
            self._filtered = list(items)
            self._filter_kwargs = {}

        def query(self, _model):
            self._filtered = list(self._items)
            self._filter_kwargs = {}
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, limit):
            if limit is not None:
                self._filtered = self._filtered[:limit]
            return self

        def filter(self, criterion, *_args, **_kwargs):
            if isinstance(criterion, tuple) and criterion[0] == "status":
                allowed = set(criterion[1])
                self._filtered = [
                    item
                    for item in self._filtered
                    if getattr(item, "status", None) in allowed
                ]
            return self

        def filter_by(self, **kwargs):
            self._filter_kwargs = kwargs
            return self

        def all(self):
            return list(self._filtered)

        def first(self):
            if not self._filter_kwargs:
                return self._filtered[0] if self._filtered else None

            for item in self._items:
                match = all(
                    getattr(item, key, object()) == value
                    for key, value in self._filter_kwargs.items()
                )
                if match:
                    return item
            return None

    class DatabaseStub:
        def __init__(self, items):
            self._items = items

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @property
        def session(self):
            return SessionStub(self._items)

    def installer(processes):
        monkeypatch.setattr(
            bp,
            "DatabaseManager",
            lambda: DatabaseStub(processes),
        )
        return processes

    return installer


def _make_process(**overrides):
    defaults = {
        "id": "proc-1",
        "status": "running",
        "command": "discover-urls",
        "progress_current": 5,
        "progress_total": 10,
        "progress_percentage": 50.0,
        "started_at": datetime(2025, 9, 26, 12, 0),
        "completed_at": None,
        "process_metadata": {},
        "error_message": None,
        "duration_seconds": 42,
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_show_background_processes_empty(
    monkeypatch, capsys, install_background_env
):
    install_background_env([])

    assert bp.show_background_processes() is True
    out = capsys.readouterr().out
    assert "No background processes found" in out


def test_show_background_processes_lists_rows(
    monkeypatch, capsys, install_background_env
):
    process = _make_process(
        id="proc-42",
        status="completed",
        command="populate-gazetteer",
        progress_current=10,
        progress_total=10,
        progress_percentage=100.0,
        started_at=datetime(2025, 9, 26, 11, 30),
        completed_at=datetime(2025, 9, 26, 11, 45),
    )
    install_background_env([process])

    assert bp.show_background_processes(limit=5) is True
    out = capsys.readouterr().out
    assert "Background Processes" in out
    assert "proc-42" in out
    assert "populate-gazetteer" in out


def test_show_active_queue_prints_running(
    monkeypatch, capsys, install_background_env
):
    process = _make_process(
        id="queue-7",
        status="running",
        command="discover-urls --force-all",
        progress_current=2,
        progress_total=8,
        progress_percentage=25.0,
        process_metadata={"publisher_uuid": "1234567890abcdef"},
    )
    install_background_env([process])

    assert bp.show_active_queue() is True
    out = capsys.readouterr().out
    assert "Active Background Processes" in out
    assert "queue-7" in out
    assert "1234567890" in out


def test_show_active_queue_handles_exception(monkeypatch, capsys):
    class BrokenDB:
        def __enter__(self):
            raise RuntimeError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(
        sys.modules,
        "src.models",
        types.SimpleNamespace(BackgroundProcess=object()),
    )
    monkeypatch.setattr(bp, "DatabaseManager", lambda: BrokenDB())

    assert bp.show_active_queue() is False
    out = capsys.readouterr().out
    assert "Error listing queue" in out


def test_show_process_status_prints_detail(
    monkeypatch, capsys, install_background_env
):
    process = _make_process(
        id="detail-9",
        status="running",
        command="populate-gazetteer",
        progress_current=3,
        progress_total=12,
        progress_percentage=25.0,
        process_metadata={"publisher_uuid": "abcdef123456"},
    )
    install_background_env([process])

    assert bp.show_process_status("detail-9") == 0
    out = capsys.readouterr().out
    assert "Process ID: detail-9" in out
    assert "populate-gazetteer" in out
    assert "3/12" in out


def test_show_process_status_not_found(
    monkeypatch, capsys, install_background_env
):
    install_background_env([])

    assert bp.show_process_status("missing") == 1
    out = capsys.readouterr().out
    assert "not found" in out.lower()


def test_handle_queue_command_wraps_result(monkeypatch):
    monkeypatch.setattr(bp, "show_active_queue", lambda: False)
    assert bp.handle_queue_command(types.SimpleNamespace()) == 1


def test_handle_status_command_routes(monkeypatch):
    calls = {}

    def fake_show_process_status(pid):
        calls["process"] = pid
        return 0

    def fake_show_background_processes(limit=20):
        calls["processes"] = True
        return True

    monkeypatch.setattr(bp, "show_process_status", fake_show_process_status)
    monkeypatch.setattr(
        bp,
        "show_background_processes",
        fake_show_background_processes,
    )
    monkeypatch.setattr(bp, "_print_database_status", lambda: 0)

    assert bp.handle_status_command(types.SimpleNamespace(process="abc")) == 0
    assert calls["process"] == "abc"

    calls.clear()
    assert bp.handle_status_command(types.SimpleNamespace(processes=True)) == 0
    assert calls["processes"] is True

    calls.clear()
    assert bp.handle_status_command(types.SimpleNamespace()) == 0
    assert not calls


def test_print_database_status_executes_queries(monkeypatch, capsys):
    executed = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt):
            sql = str(stmt)
            executed.append(sql)

            if "FROM candidate_links" in sql and "GROUP BY status" in sql:
                return [("pending", 3)]
            if "FROM articles" in sql and "GROUP BY status" in sql:
                return [("processed", 5)]
            if (
                "FROM candidate_links cl" in sql
                and "GROUP BY cl.source_name" in sql
            ):
                return [("Example News", "Boone", "Columbia", 7)]
            if (
                "FROM candidate_links cl" in sql
                and "COUNT(DISTINCT cl.id)" in sql
            ):
                return [("Boone", 4, 10)]

            return []

    class FakeEngine:
        def connect(self):
            return FakeConn()

    class FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        engine = FakeEngine()

    monkeypatch.setattr(bp, "DatabaseManager", lambda: FakeDB())

    assert bp._print_database_status() == 0
    output = capsys.readouterr().out
    assert "Candidate Links Status" in output
    assert len(executed) == 4


def test_print_database_status_on_error(monkeypatch, capsys):
    class FakeDB:
        def __enter__(self):
            raise RuntimeError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(bp, "DatabaseManager", lambda: FakeDB())

    assert bp._print_database_status() == 1
    output = capsys.readouterr().out
    assert "Failed to get status" in output


def test_print_process_table_handles_missing_fields(capsys):
    process = _make_process(
        id="row-1",
        status="pending",
        command="crawl",
        progress_current=0,
        progress_total=None,
        progress_percentage=None,
        started_at=None,
    )

    bp._print_process_table([process])
    out = capsys.readouterr().out
    assert "row-1" in out
    assert "crawl" in out


def test_print_process_detail_running_duration(capsys):
    process = _make_process(
        status="running",
        command="discover",
        completed_at=None,
        process_metadata={"publisher_uuid": "abc"},
    )
    process.error_message = "oops"

    bp._print_process_detail(process)
    out = capsys.readouterr().out
    assert "Process ID" in out
    assert "Duration" in out
    assert "oops" in out


def test_format_progress_with_details():
    process = _make_process(
        progress_current=4,
        progress_total=8,
        progress_percentage=50.0,
    )
    assert bp._format_progress(process, detailed=True) == "4/8 (50.0%)"

    process_no_total = _make_process(
        progress_total=None,
        progress_percentage=None,
    )
    assert bp._format_progress(process_no_total) == "5"
