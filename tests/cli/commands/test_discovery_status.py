from types import SimpleNamespace

import pandas as pd
import pytest

from src.cli.commands import discovery_status


class _DummyConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


@pytest.fixture
def stubbed_db(monkeypatch):
    """Provide deterministic DatabaseManager/safe_execute behavior."""

    query_map: dict[str, list[tuple]] = {}

    class _FakeEngine:
        def connect(self):
            return _DummyConnection()

    def fake_db_manager(*_args, **_kwargs):
        return SimpleNamespace(engine=_FakeEngine())

    def fake_safe_execute(_conn, stmt, _params=None):
        sql = str(stmt)
        for key, rows in query_map.items():
            if key in sql:
                return _FakeResult(rows)
        raise AssertionError(f"No stubbed result for query: {sql}")

    monkeypatch.setattr(discovery_status, "DatabaseManager", fake_db_manager)
    monkeypatch.setattr(discovery_status, "safe_execute", fake_safe_execute)

    return query_map


def _install_discovery_stub(monkeypatch, due_count=1, verbose_sources=1):
    calls: list[bool] = []

    df_all = pd.DataFrame(
        [
            {"name": "Never Attempted", "discovery_attempted": 0},
            {"name": "Tried Once", "discovery_attempted": 1},
        ]
    )
    df_due = pd.DataFrame(
        [
            {"name": f"Due Source {i}", "discovery_attempted": 1}
            for i in range(due_count)
        ]
    )

    if due_count == 0:
        df_due = pd.DataFrame(columns=["name", "discovery_attempted"])

    def fake_get_sources(self, dataset_label=None, due_only=False, **_kwargs):
        calls.append(due_only)
        if due_only:
            return df_due, {"sources_skipped": 2}
        return df_all.head(verbose_sources), {"sources_skipped": 0}

    class _DiscoveryStub:
        def __init__(self, *_args, **_kwargs):
            self.get_sources_to_process = fake_get_sources.__get__(self)

    monkeypatch.setattr("src.crawler.discovery.NewsDiscovery", _DiscoveryStub)
    return calls


def test_discovery_status_verbose_summary(stubbed_db, monkeypatch, capsys):
    """CLI should print dataset + verbose sections when data exists."""

    stubbed_db["FROM datasets"] = [("Dataset A", "dataset-a", "2025-01-01")]
    stubbed_db["SELECT COUNT(*) FROM sources"] = [(5,)]
    stubbed_db["DATE(discovered_at)"] = [("2025-01-01", 12)]

    calls = _install_discovery_stub(monkeypatch)

    args = SimpleNamespace(dataset=None, verbose=True)
    exit_code = discovery_status.handle_discovery_status_command(args)

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Dataset A" in output
    assert "Total Sources (all datasets): 5" in output
    assert "Sources due now: 1" in output
    assert "Recent Discovery Activity" in output
    assert calls == [False, True]


def test_discovery_status_warns_when_no_sources_due(stubbed_db, monkeypatch, capsys):
    """When nothing is due, CLI should emit guidance about --force-all."""

    stubbed_db["FROM datasets"] = [("Dataset B", "dataset-b", "2024-12-12")]
    stubbed_db["COUNT(DISTINCT s.id)"] = [(3,)]
    stubbed_db["DATE(discovered_at)"] = []

    _install_discovery_stub(monkeypatch, due_count=0)

    args = SimpleNamespace(dataset="metro", verbose=False)
    exit_code = discovery_status.handle_discovery_status_command(args)

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Sources due now: 0" in output
    assert "No sources are currently due" in output
    assert "--dataset metro" in output


def test_discovery_status_returns_error_when_no_sources(
    stubbed_db, monkeypatch, capsys
):
    """If the database has zero sources, CLI should exit non-zero."""

    stubbed_db["FROM datasets"] = []
    stubbed_db["SELECT COUNT(*) FROM sources"] = [(0,)]

    _install_discovery_stub(monkeypatch)

    args = SimpleNamespace(dataset=None, verbose=False)
    exit_code = discovery_status.handle_discovery_status_command(args)

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "No sources found" in output


def test_to_int_handles_invalid_values():
    assert discovery_status._to_int("42") == 42
    assert discovery_status._to_int(None, default=5) == 5
    assert discovery_status._to_int("not-a-number", default=7) == 7


def test_discovery_status_handles_exception(stubbed_db, monkeypatch, capsys):
    stubbed_db["FROM datasets"] = []
    stubbed_db["SELECT COUNT(*) FROM sources"] = [(1,)]
    stubbed_db["DATE(discovered_at)"] = []

    class _BrokenDiscovery:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.crawler.discovery.NewsDiscovery",
        _BrokenDiscovery,
    )

    args = SimpleNamespace(dataset=None, verbose=False)
    exit_code = discovery_status.handle_discovery_status_command(args)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Discovery status command failed" in output
