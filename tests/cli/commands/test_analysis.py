from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any, Optional

import pytest

import src.cli.commands.analysis as analysis
from src.services.classification_service import ClassificationStats


class DummyDatabase:
    def __init__(self) -> None:
        self.session = object()
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ServiceStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply_classification(self, *_args, **kwargs) -> ClassificationStats:
        self.calls.append(kwargs)
        return ClassificationStats(
            processed=5,
            labeled=4,
            skipped=1,
            errors=0,
        )


@pytest.fixture()
def db_stub(monkeypatch):
    db = DummyDatabase()
    monkeypatch.setattr(analysis, "DatabaseManager", lambda: db)
    return db


@pytest.fixture()
def classifier_invocations(monkeypatch):
    creations: list[Path] = []

    class _Classifier:
        model_version = "dummy-version"
        model_identifier = "dummy-model"

        def __init__(self, model_path: Path | str) -> None:
            creations.append(Path(model_path))

    monkeypatch.setattr(analysis, "ArticleClassifier", _Classifier)
    return creations


@pytest.fixture()
def service_stub(monkeypatch):
    stub = ServiceStub()
    monkeypatch.setattr(
        analysis,
        "ArticleClassificationService",
        lambda session: stub,
    )
    return stub


def _default_args(**overrides) -> Namespace:
    defaults = dict(
        limit=None,
        label_version="default",
        model_path="models",
        model_version=None,
        statuses=["cleaned", "local"],
        batch_size=16,
        top_k=2,
        dry_run=False,
        force=False,
        report_path=None,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


def test_handle_analysis_success_without_report(
    db_stub, classifier_invocations, service_stub, capsys
):
    args = _default_args(limit=10, batch_size=32, top_k=3)

    exit_code = analysis.handle_analysis_command(args)

    assert exit_code == 0
    assert db_stub.closed is True
    assert len(classifier_invocations) == 1

    invocation = service_stub.calls.pop()
    assert invocation["label_version"] == "default"
    assert invocation["statuses"] == ["cleaned", "local"]
    assert invocation["limit"] == 10
    assert invocation["batch_size"] == 32
    assert invocation["top_k"] == 3
    assert invocation["dry_run"] is False
    assert invocation["include_existing"] is False

    stdout = capsys.readouterr().out
    assert "=== Classification Summary ===" in stdout
    assert "Report generation skipped" in stdout


def test_handle_analysis_dry_run_generates_report(
    classifier_invocations,
    service_stub,
    db_stub,
    monkeypatch,
    tmp_path,
    capsys,
):
    stats = ClassificationStats(
        processed=2,
        labeled=2,
        skipped=0,
        errors=0,
    )
    stats.proposed_labels = [
        {
            "article_id": "101",
            "url": "https://example.com/article",
            "primary": "local",
            "alternate": "state",
        }
    ]

    service_stub.apply_classification = (  # type: ignore[assignment]
        lambda *_args, **_kwargs: stats
    )

    before_snapshot = {
        "101": {
            "url": "https://example.com/article",
            "primary": "old-local",
            "alternate": "state",
        }
    }
    snapshot_calls: list[tuple[Any, ...]] = []

    def fake_snapshot(session, label_version, statuses):
        snapshot_calls.append((session, label_version, statuses))
        return before_snapshot

    monkeypatch.setattr(analysis, "_snapshot_labels", fake_snapshot)

    report_path = tmp_path / "dry_run_changes.csv"
    args = _default_args(
        dry_run=True,
        report_path=str(report_path),
        model_path=tmp_path,
    )

    exit_code = analysis.handle_analysis_command(args)

    assert exit_code == 0
    assert db_stub.closed is True
    assert report_path.exists()

    contents = report_path.read_text(encoding="utf-8").splitlines()
    assert contents[0].startswith("article_id")
    assert "101" in contents[1]
    assert "old-local" in contents[1]
    assert "local" in contents[1]

    stdout = capsys.readouterr().out
    assert "Dry-run mode: no labels were persisted." in stdout
    assert "Rows written: 1" in stdout
    assert "=== Label Change Report ===" in stdout

    assert snapshot_calls


def test_handle_analysis_persisted_report_generates_csv(
    classifier_invocations,
    service_stub,
    db_stub,
    monkeypatch,
    tmp_path,
    capsys,
):
    before_snapshot = {
        "101": {
            "url": "https://example.com/article",
            "primary": "old",
            "alternate": "older",
        }
    }
    after_snapshot = {
        "101": {
            "url": "https://example.com/article",
            "primary": "new",
            "alternate": "older",
        }
    }
    snapshots = [before_snapshot, after_snapshot]
    snapshot_calls: list[tuple[Any, str, list[str] | None]] = []

    def fake_snapshot(session, label_version, statuses):
        snapshot_calls.append((session, label_version, statuses))
        return snapshots[len(snapshot_calls) - 1]

    monkeypatch.setattr(analysis, "_snapshot_labels", fake_snapshot)

    captured_changes: list[tuple] = []

    def fake_compute(before, after, label_version):
        captured_changes.append((before, after, label_version))
        return [
            {
                "article_id": "101",
                "url": "https://example.com/article",
                "label_version": label_version,
                "old_primary_label": "old",
                "new_primary_label": "new",
                "old_alternate_label": "older",
                "new_alternate_label": "older",
            }
        ]

    monkeypatch.setattr(analysis, "_compute_label_changes", fake_compute)

    write_calls: list[tuple[Path, list[dict[str, str]]]] = []

    def fake_write(path, rows):
        target = Path(path)
        write_calls.append((target, rows))
        return target

    monkeypatch.setattr(analysis, "_write_label_changes", fake_write)

    report_path = tmp_path / "persisted_changes.csv"
    args = _default_args(report_path=str(report_path), dry_run=False)

    exit_code = analysis.handle_analysis_command(args)

    assert exit_code == 0
    assert db_stub.closed is True
    assert len(snapshot_calls) == 2
    assert snapshot_calls[0][1:] == ("default", ["cleaned", "local"])
    assert captured_changes
    assert write_calls and write_calls[0][0] == report_path

    stdout = capsys.readouterr().out
    assert "Rows written: 1" in stdout
    assert f"Location: {report_path}" in stdout
    assert "label change report" in stdout.lower()


def test_handle_analysis_returns_error_when_classifier_fails(monkeypatch):
    def broken_classifier(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(analysis, "ArticleClassifier", broken_classifier)

    args = _default_args(model_path="models/bad")

    exit_code = analysis.handle_analysis_command(args)

    assert exit_code == 1


@pytest.mark.parametrize(
    "raw_statuses, expected",
    [
        (None, ["cleaned", "local"]),
        ([], ["cleaned", "local"]),
        (["ALL"], None),
        (["local", "Local", " wire "], ["local", "wire"]),
        (["", "  "], ["cleaned", "local"]),
    ],
)
def test_resolve_statuses_handles_edge_cases(raw_statuses, expected):
    result = analysis._resolve_statuses(raw_statuses)
    assert result == expected


def test_resolve_statuses_preserves_order_unique():
    statuses = analysis._resolve_statuses(
        [" local", "cleaned", "Local", "state"]
    )
    assert statuses == ["local", "cleaned", "state"]


@pytest.mark.parametrize(
    "statuses, expected",
    [
        (None, None),
        (["cleaned", "wire", "local"], ["cleaned", "local"]),
        (["wire", "obituary"], []),
        (["LOCAL"], ["LOCAL"]),
    ],
)
def test_filtered_statuses_removes_excluded(statuses, expected):
    assert analysis._filtered_statuses(statuses) == expected


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.calls = 0

    def execute(self, stmt):  # pragma: no cover - exercised in tests
        self.calls += 1
        return _FakeResult(self._rows)


def test_snapshot_labels_returns_snapshot_when_statuses_none():
    rows = [
        (1, "https://example.com/a", "local", "state"),
        (2, "https://example.com/b", None, "county"),
    ]
    session = _FakeSession(rows)

    result = analysis._snapshot_labels(session, "default", None)

    assert session.calls == 1
    assert result == {
        "1": {
            "url": "https://example.com/a",
            "primary": "local",
            "alternate": "state",
        },
        "2": {
            "url": "https://example.com/b",
            "primary": None,
            "alternate": "county",
        },
    }


def test_snapshot_labels_short_circuits_on_empty_statuses():
    session = _FakeSession([(1, "url", "p", "a")])

    result = analysis._snapshot_labels(session, "default", [])

    assert result == {}
    assert session.calls == 0


def test_snapshot_labels_returns_rows_for_explicit_statuses():
    rows = [(5, "https://example.com", "primary", "alt")]
    session = _FakeSession(rows)

    result = analysis._snapshot_labels(session, "v1", ["cleaned"])

    assert session.calls == 1
    assert result["5"]["primary"] == "primary"


def test_compute_label_changes_detects_primary_updates():
    before: dict[str, dict[str, Optional[str]]] = {
        "1": {
            "url": "https://example.com/a",
            "primary": "old",
            "alternate": "alt",
        }
    }
    after: dict[str, dict[str, Optional[str]]] = {
        "1": {
            "url": "https://example.com/a",
            "primary": "new",
            "alternate": "alt",
        },
        "2": {
            "url": "https://example.com/b",
            "primary": "fresh",
            "alternate": None,
        },
    }

    changes = analysis._compute_label_changes(before, after, "default")

    assert changes == [
        {
            "article_id": "1",
            "url": "https://example.com/a",
            "label_version": "default",
            "old_primary_label": "old",
            "new_primary_label": "new",
            "old_alternate_label": "alt",
            "new_alternate_label": "alt",
        },
        {
            "article_id": "2",
            "url": "https://example.com/b",
            "label_version": "default",
            "old_primary_label": "",
            "new_primary_label": "fresh",
            "old_alternate_label": "",
            "new_alternate_label": "",
        },
    ]


def test_compute_dry_run_changes_uses_fallbacks():
    before: dict[str, dict[str, Optional[str]]] = {
        "10": {
            "url": "https://example.com/old",
            "primary": "old",
            "alternate": "alt",
        }
    }
    proposals = [
        {
            "article_id": 10,
            "primary": "old",
            "alternate": "alt",
        },
        {
            "article_id": 10,
            "primary": "updated",
            "alternate": "alt",
        },
        {
            "article_id": "11",
            "primary": 5,
            "alternate": None,
            "url": "https://example.com/new",
        },
    ]

    changes = analysis._compute_dry_run_changes(before, proposals, "default")

    assert changes == [
        {
            "article_id": "10",
            "url": "https://example.com/old",
            "label_version": "default",
            "old_primary_label": "old",
            "new_primary_label": "updated",
            "old_alternate_label": "alt",
            "new_alternate_label": "alt",
        },
        {
            "article_id": "11",
            "url": "https://example.com/new",
            "label_version": "default",
            "old_primary_label": "",
            "new_primary_label": "5",
            "old_alternate_label": "",
            "new_alternate_label": "",
        },
    ]


def test_write_label_changes_creates_csv(tmp_path):
    report_path = tmp_path / "report.csv"
    rows = [
        {
            "article_id": "1",
            "url": "https://example.com",
            "label_version": "default",
            "old_primary_label": "old",
            "new_primary_label": "new",
            "old_alternate_label": "alt",
            "new_alternate_label": "alt",
        }
    ]

    written_path = analysis._write_label_changes(report_path, rows)

    assert written_path == report_path
    contents = report_path.read_text(encoding="utf-8").splitlines()
    assert contents[0].startswith("article_id")
    assert "new" in contents[1]


def test_handle_analysis_no_label_changes_reports_skip(
    classifier_invocations,
    service_stub,
    db_stub,
    monkeypatch,
    tmp_path,
    capsys,
):
    stats = ClassificationStats(processed=1, labeled=1, skipped=0, errors=0)
    service_stub.apply_classification = (  # type: ignore[assignment]
        lambda *_args, **_kwargs: stats
    )

    snapshot = {
        "1": {
            "url": "https://example.com",
            "primary": "local",
            "alternate": "state",
        }
    }
    snapshots = [snapshot, snapshot]

    def fake_snapshot(session, label_version, statuses):
        return snapshots.pop(0)

    monkeypatch.setattr(analysis, "_snapshot_labels", fake_snapshot)
    monkeypatch.setattr(
        analysis,
        "_compute_label_changes",
        lambda before, after, version: [],
    )
    monkeypatch.setattr(
        analysis,
        "_write_label_changes",
        lambda path, rows: path,
    )

    report_path = tmp_path / "no_changes.csv"
    args = _default_args(report_path=str(report_path))

    exit_code = analysis.handle_analysis_command(args)

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "No label changes detected" in stdout
