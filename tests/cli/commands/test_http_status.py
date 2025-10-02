from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Sequence

import pytest

import src.cli.commands.http_status as http_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    http_status.add_http_status_parser(subparsers)
    return parser


class _FakeResult:
    def __init__(self, rows: Sequence[Any]):
        self._rows = list(rows)

    def fetchall(self) -> List[Any]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self, parent: "_FakeDatabase"):
        self._parent = parent

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args) -> None:  # pragma: no cover - no cleanup
        return None

    def execute(self, sql, params):  # type: ignore[override]
        sql_text = str(sql)
        if "FROM sources" in sql_text:
            self._parent.lookup_calls.append(params)
            if self._parent.lookup_error:
                raise RuntimeError("lookup boom")
            rows = [(sid,) for sid in self._parent.host_lookup]
            return _FakeResult(rows)

        self._parent.query_calls.append((sql_text, params))
        if self._parent.query_error:
            raise RuntimeError("query boom")
        return _FakeResult(self._parent.status_rows)


class _FakeDatabase:
    def __init__(
        self,
        *,
        status_rows: List[Dict[str, Any]] | None = None,
        host_lookup: List[str] | None = None,
        query_error: bool = False,
        lookup_error: bool = False,
    ) -> None:
        self.status_rows = status_rows or []
        self.host_lookup = host_lookup or []
        self.query_error = query_error
        self.lookup_error = lookup_error
        self.query_calls: List[tuple[str, Dict[str, Any]]] = []
        self.lookup_calls: List[Dict[str, Any]] = []

    def __enter__(self) -> "_FakeDatabase":
        return self

    def __exit__(self, *_args) -> None:  # pragma: no cover - no cleanup
        return None

    @property
    def engine(self) -> "_FakeDatabase":
        return self

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


_SAMPLE_ROW: Dict[str, Any] = {
    "id": 1,
    "source_id": "src-1",
    "source_url": "https://example.com",
    "attempted_url": "https://example.com/article",
    "discovery_method": "RSS",
    "status_code": 200,
    "status_category": "SUCCESS",
    "response_time_ms": 123,
    "content_length": 4567,
    "error_message": None,
    "timestamp": "2025-09-29T08:00:00",
}


def _install_db(
    monkeypatch: pytest.MonkeyPatch, fake_db: _FakeDatabase
) -> None:
    monkeypatch.setattr(http_status, "DatabaseManager", lambda: fake_db)


def _capture_print(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    printed: List[str] = []

    def fake_print(*parts, **_kwargs) -> None:
        printed.append(" ".join(str(part) for part in parts))

    monkeypatch.setattr("builtins.print", fake_print)
    return printed


def test_add_http_status_parser_registers_command():
    parser = _build_parser()

    args = parser.parse_args(["dump-http-status", "--source-id", "abc"])

    assert args.func is http_status.handle_http_status_command
    assert args.limit == 50
    assert args.format == "table"
    assert args.lookup_host is False


def test_handle_http_status_warns_and_prints_table(monkeypatch):
    fake_db = _FakeDatabase(status_rows=[_SAMPLE_ROW])
    _install_db(monkeypatch, fake_db)

    printed = _capture_print(monkeypatch)
    args = _build_parser().parse_args(["dump-http-status"])

    exit_code = http_status.handle_http_status_command(args)

    assert exit_code == 0
    assert printed and printed[0].startswith("Warning")
    assert any("source_id" in line for line in printed[1:])
    assert fake_db.query_calls
    assert fake_db.query_calls[0][1]["limit"] == 50


def test_handle_http_status_filters_by_source_id(monkeypatch):
    fake_db = _FakeDatabase(status_rows=[_SAMPLE_ROW])
    _install_db(monkeypatch, fake_db)

    printed = _capture_print(monkeypatch)
    args = _build_parser().parse_args(
        [
            "dump-http-status",
            "--source-id",
            "src-123",
            "--limit",
            "5",
        ]
    )

    exit_code = http_status.handle_http_status_command(args)

    assert exit_code == 0
    assert printed and not printed[0].startswith("Warning")
    sql, params = fake_db.query_calls[0]
    assert "http_status_tracking" in sql
    assert params == {"limit": 5, "source_id": "src-123"}


def test_handle_http_status_adds_host_like_filter(monkeypatch):
    fake_db = _FakeDatabase(status_rows=[_SAMPLE_ROW])
    _install_db(monkeypatch, fake_db)

    printed = _capture_print(monkeypatch)
    args = _build_parser().parse_args(
        ["dump-http-status", "--host", "example.com"]
    )

    exit_code = http_status.handle_http_status_command(args)

    assert exit_code == 0
    assert printed and not printed[0].startswith("Warning")
    sql, params = fake_db.query_calls[0]
    assert params["host_like"] == "%example.com%"
    assert {"limit", "host_like"} <= set(params.keys())


def test_handle_http_status_resolves_lookup_host(monkeypatch):
    fake_db = _FakeDatabase(
        status_rows=[_SAMPLE_ROW],
        host_lookup=["id-1", "id-2"],
    )
    _install_db(monkeypatch, fake_db)

    printed = _capture_print(monkeypatch)
    args = _build_parser().parse_args(
        ["dump-http-status", "--host", "Example.com", "--lookup-host"]
    )

    exit_code = http_status.handle_http_status_command(args)

    assert exit_code == 0
    assert printed and not printed[0].startswith("Warning")
    assert fake_db.lookup_calls == [
        {"h": "%Example.com%", "h_norm": "%example.com%"}
    ]
    sql, params = fake_db.query_calls[0]
    assert "source_id IN" in sql
    assert params["sid0"] == "id-1"
    assert params["sid1"] == "id-2"
    assert "host_like" not in params


def test_handle_http_status_outputs_json(monkeypatch):
    fake_db = _FakeDatabase(status_rows=[_SAMPLE_ROW])
    _install_db(monkeypatch, fake_db)

    printed = _capture_print(monkeypatch)
    args = _build_parser().parse_args(
        ["dump-http-status", "--source-id", "src-1", "--format", "json"]
    )

    exit_code = http_status.handle_http_status_command(args)

    assert exit_code == 0
    assert printed == [json.dumps([_SAMPLE_ROW], default=str, indent=2)]


def test_handle_http_status_handles_exception(monkeypatch):
    fake_db = _FakeDatabase(query_error=True)
    _install_db(monkeypatch, fake_db)

    printed = _capture_print(monkeypatch)
    exceptions: List[str] = []
    monkeypatch.setattr(
        http_status,
        "logger",
        SimpleNamespace(exception=lambda message: exceptions.append(message)),
    )

    args = _build_parser().parse_args(
        ["dump-http-status", "--host", "example.com"]
    )

    exit_code = http_status.handle_http_status_command(args)

    assert exit_code == 1
    assert exceptions == ["Failed to query http_status_tracking"]
    assert any("query boom" in line for line in printed)
