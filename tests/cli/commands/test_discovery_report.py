from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import src.cli.commands.discovery_report as discovery_report


class FakeTelemetry:
    def __init__(self, report: dict[str, Any]):
        self.report = report
        self.calls: list[dict[str, Any]] = []

    def get_discovery_outcomes_report(self, **kwargs):
        self.calls.append(kwargs)
        return self.report


class FakeDiscovery:
    def __init__(self, telemetry: FakeTelemetry):
        self.telemetry = telemetry


def _patch_discovery(monkeypatch, report: dict[str, Any]):
    telemetry = FakeTelemetry(report)
    stub = ModuleType("src.crawler.discovery")
    stub.NewsDiscovery = lambda: FakeDiscovery(telemetry)
    monkeypatch.setitem(sys.modules, "src.crawler.discovery", stub)
    return telemetry


def test_handle_discovery_report_summary_default(monkeypatch, capsys):
    report = {
        "summary": {
            "total_sources": 5,
            "technical_success_rate": 80,
            "content_success_rate": 60,
            "total_new_articles": 12,
            "avg_discovery_time_ms": 123.45,
        },
        "outcome_breakdown": [
            {"outcome": "SUCCESS", "count": 8, "percentage": 80},
            {"outcome": "FAIL", "count": 2, "percentage": 20},
        ],
        "top_performing_sources": [
            {
                "source_name": "Source A",
                "content_success_rate": 90,
                "total_new_articles": 6,
            }
        ],
    }
    telemetry = _patch_discovery(monkeypatch, report)

    args = SimpleNamespace(
        operation_id=None,
        format="summary",
    )

    exit_code = discovery_report.handle_discovery_report_command(args)

    assert exit_code == 0
    assert telemetry.calls == [{"operation_id": None, "hours_back": 24}], (
        "Default hours_back should be applied"
    )

    output = capsys.readouterr().out
    assert "Discovery Outcomes Summary" in output
    assert "Total sources processed: 5" in output
    assert "SUCCESS: 8 (80%)" in output
    assert "Source A: 90% success, 6 articles" in output


def test_handle_discovery_report_detailed(monkeypatch, capsys):
    report = {
        "summary": {
            "total_sources": 2,
            "technical_success_rate": 100,
            "content_success_rate": 50,
            "total_new_articles": 4,
            "avg_discovery_time_ms": None,
            "technical_success_count": 3,
            "content_success_count": 2,
            "technical_failure_count": 1,
            "total_articles_found": 5,
            "total_duplicate_articles": 1,
            "total_expired_articles": 0,
        },
        "outcome_breakdown": [],
        "top_performing_sources": [
            {
                "source_name": "Source B",
                "attempts": 3,
                "content_successes": 2,
                "content_success_rate": 66,
                "total_new_articles": 4,
            }
        ],
    }
    _patch_discovery(monkeypatch, report)

    args = SimpleNamespace(
        operation_id="op-123",
        hours_back=12,
        format="detailed",
    )

    exit_code = discovery_report.handle_discovery_report_command(args)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Detailed Statistics" in output
    assert "Technical successes: 3" in output
    assert "Source B:" in output
    assert "Attempts: 3" in output


def test_handle_discovery_report_json(monkeypatch, capsys):
    report = {"summary": {"total_sources": 1}, "outcome_breakdown": []}
    _patch_discovery(monkeypatch, report)

    args = SimpleNamespace(operation_id="op-1", hours_back=6, format="json")

    exit_code = discovery_report.handle_discovery_report_command(args)

    assert exit_code == 0
    output = capsys.readouterr().out.strip()
    parsed = json.loads(output)
    assert parsed == report


def test_handle_discovery_report_handles_report_errors(monkeypatch, capsys):
    report = {"error": "upstream issue"}
    _patch_discovery(monkeypatch, report)

    args = SimpleNamespace(operation_id=None, hours_back=3, format="summary")

    exit_code = discovery_report.handle_discovery_report_command(args)

    assert exit_code == 1
    assert capsys.readouterr().out.strip() == "Error generating report: upstream issue"


def test_handle_discovery_report_handles_exceptions(monkeypatch, capsys):
    class FailingDiscovery:
        def __init__(self):
            raise RuntimeError("boom")

    recorded: dict[str, Any] = {}

    class DummyLogger:
        def exception(self, message):
            recorded["message"] = message

    stub = ModuleType("src.crawler.discovery")
    stub.NewsDiscovery = FailingDiscovery
    monkeypatch.setitem(sys.modules, "src.crawler.discovery", stub)
    monkeypatch.setattr(discovery_report, "logger", DummyLogger())

    args = SimpleNamespace(operation_id=None, hours_back=1, format="summary")

    exit_code = discovery_report.handle_discovery_report_command(args)

    assert exit_code == 1
    output = capsys.readouterr().out.strip()
    assert output.startswith("Discovery report failed: boom")
    assert recorded["message"] == "Discovery report command failed"
