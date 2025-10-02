from __future__ import annotations

import argparse
import builtins
import types

import pytest

import src.cli.commands.discovery as discovery
import src.crawler.discovery as crawler_discovery


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    discovery.add_discovery_parser(subparsers)
    return parser


def _base_stats(**overrides):
    stats = {
        "sources_processed": 0,
        "sources_succeeded": 0,
        "sources_failed": 0,
        "total_candidates_discovered": 0,
    }
    stats.update(overrides)
    return stats


def _make_args(**overrides):
    defaults = dict(
        source_uuid=None,
        source_uuids=None,
        legacy_article_limit=None,
        max_articles=50,
        days_back=7,
        dataset=None,
        source_limit=None,
        source_filter=None,
        host=None,
        city=None,
        county=None,
        due_only=True,
        force_all=False,
        host_limit=None,
        existing_article_limit=None,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _silence_logging(monkeypatch):
    dummy_logger = types.SimpleNamespace(
        info=lambda *_a, **_k: None,
        exception=lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        discovery,
        "logging",
        types.SimpleNamespace(getLogger=lambda *_a, **_k: dummy_logger),
    )


def _silence_print(monkeypatch):
    monkeypatch.setattr(builtins, "print", lambda *a, **k: None)


def test_add_discovery_parser_defaults():
    parser = _build_parser()

    args = parser.parse_args(["discover-urls"])  # no extra flags

    assert args.func is discovery.handle_discovery_command
    assert args.max_articles == 50
    assert args.days_back == 7
    assert args.due_only is True
    assert args.force_all is False
    assert args.source_filter is None
    assert args.source_limit is None
    assert args.legacy_article_limit is None
    assert args.source_uuids is None


def test_add_discovery_parser_aliases():
    parser = _build_parser()

    args = parser.parse_args(
        [
            "discover-urls",
            "--source",
            "gazette",
            "--source-uuids",
            "id-1",
            "id-2",
            "--article-limit",
            "25",
            "--host-limit",
            "3",
        ]
    )

    assert args.source_filter == "gazette"
    assert args.source_uuids == ["id-1", "id-2"]
    # legacy alias sets legacy_article_limit but not max_articles
    assert args.legacy_article_limit == 25
    assert args.host_limit == 3


@pytest.mark.parametrize(
    "source_uuid, source_uuids, expected",
    [
        (None, None, []),
        ("one", None, ["one"]),
        (None, ["two"], ["two"]),
        ("first", ["second", "third"], ["first", "second", "third"]),
    ],
)
def test_collect_source_uuids(source_uuid, source_uuids, expected):
    assert discovery._collect_source_uuids(source_uuid, source_uuids) == expected


def test_handle_discovery_command_legacy_limit_sets_existing(monkeypatch):
    captured = {}

    class FakeDiscovery:
        def __init__(self, max_articles_per_source, days_back):
            captured["init"] = {
                "max_articles_per_source": max_articles_per_source,
                "days_back": days_back,
            }
            self.telemetry = types.SimpleNamespace(
                list_active_operations=lambda: [],
                get_failure_summary=lambda *_a, **_k: {
                    "total_failures": 0,
                    "failure_types": {},
                },
            )

        def run_discovery(self, **kwargs):
            captured["run"] = kwargs
            return _base_stats()

    _silence_logging(monkeypatch)
    _silence_print(monkeypatch)

    monkeypatch.setattr(
        crawler_discovery,
        "NewsDiscovery",
        FakeDiscovery,
    )

    args = _make_args(
        legacy_article_limit=20,
        existing_article_limit=None,
        max_articles=99,
    )

    exit_code = discovery.handle_discovery_command(args)
    assert exit_code == 0
    assert captured["init"]["max_articles_per_source"] == 20
    assert captured["run"]["existing_article_limit"] == 20


def test_handle_discovery_command_force_all_disables_due_only(monkeypatch):
    captured = {}

    class FakeDiscovery:
        def __init__(self, max_articles_per_source, days_back):
            captured["init"] = {
                "max_articles_per_source": max_articles_per_source,
                "days_back": days_back,
            }
            self.telemetry = types.SimpleNamespace(
                list_active_operations=lambda: [],
                get_failure_summary=lambda *_a, **_k: {
                    "total_failures": 0,
                    "failure_types": {},
                },
            )

        def run_discovery(self, **kwargs):
            captured["run"] = kwargs
            return _base_stats()

    _silence_logging(monkeypatch)
    _silence_print(monkeypatch)

    monkeypatch.setattr(
        crawler_discovery,
        "NewsDiscovery",
        FakeDiscovery,
    )

    args = _make_args(due_only=True, force_all=True)

    exit_code = discovery.handle_discovery_command(args)
    assert exit_code == 0
    assert captured["run"]["due_only"] is False


def test_handle_discovery_command_reports_success(monkeypatch, capsys):
    captured = {}
    stats = _base_stats(
        sources_available=5,
        sources_due=3,
        sources_skipped=1,
        sources_processed=2,
        sources_succeeded=2,
        sources_failed=0,
        sources_with_content=2,
        sources_no_content=0,
        total_candidates_discovered=8,
    )

    class FakeDiscovery:
        def __init__(self, max_articles_per_source, days_back):
            captured["init"] = {
                "max_articles_per_source": max_articles_per_source,
                "days_back": days_back,
            }
            self.telemetry = types.SimpleNamespace(
                list_active_operations=lambda: [],
                get_failure_summary=lambda *_a, **_k: {
                    "total_failures": 0,
                    "failure_types": {},
                },
            )

        def run_discovery(self, **kwargs):
            captured["run"] = kwargs
            return stats

    log_messages = []

    def fake_get_logger(*_a, **_k):
        return types.SimpleNamespace(
            info=lambda message: log_messages.append(message),
            exception=lambda *_a, **_k: log_messages.append("exception"),
        )

    monkeypatch.setattr(
        discovery,
        "logging",
        types.SimpleNamespace(getLogger=fake_get_logger),
    )

    monkeypatch.setattr(crawler_discovery, "NewsDiscovery", FakeDiscovery)

    args = _make_args(
        dataset="daily",
        source_limit=3,
        source_filter="gazette",
        source_uuid="uuid-one",
        source_uuids=["uuid-two"],
        host="example.com",
        city="Columbia",
        county="Boone",
        host_limit=4,
        existing_article_limit=12,
        max_articles=70,
        days_back=9,
    )

    exit_code = discovery.handle_discovery_command(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert captured["init"] == {
        "max_articles_per_source": 70,
        "days_back": 9,
    }
    assert captured["run"] == {
        "dataset_label": "daily",
        "source_limit": 3,
        "source_filter": "gazette",
        "source_uuids": ["uuid-one", "uuid-two"],
        "due_only": True,
        "host_filter": "example.com",
        "city_filter": "Columbia",
        "county_filter": "Boone",
        "host_limit": 4,
        "existing_article_limit": 12,
    }

    assert "Sources available: 5" in out
    assert "Sources processed: 2" in out
    assert "Technical success rate: 100.0%" in out
    assert "Average candidates per source: 4.0" in out
    assert any("Starting URL discovery pipeline" in msg for msg in log_messages)


def test_handle_discovery_command_reports_failures(monkeypatch, capsys):
    captured = {}
    telemetry_calls = {"listed": 0, "summary_ids": []}
    stats = _base_stats(
        sources_processed=2,
        sources_succeeded=1,
        sources_failed=1,
        total_candidates_discovered=5,
    )

    class FakeTelemetry:
        def list_active_operations(self):
            telemetry_calls["listed"] += 1
            return [{"operation_id": "op-123"}]

        def get_failure_summary(self, operation_id):
            telemetry_calls["summary_ids"].append(operation_id)
            return {
                "total_failures": 3,
                "most_common_failure": "timeout",
                "failure_types": {
                    "timeout": 2,
                    "http_error": 1,
                },
            }

    class FakeDiscovery:
        def __init__(self, max_articles_per_source, days_back):
            captured["init"] = {
                "max_articles_per_source": max_articles_per_source,
                "days_back": days_back,
            }
            self.telemetry = FakeTelemetry()

        def run_discovery(self, **kwargs):
            captured["run"] = kwargs
            return stats

    log_messages = []

    def fake_get_logger(*_a, **_k):
        return types.SimpleNamespace(
            info=lambda message: log_messages.append(message),
            exception=lambda *_a, **_k: log_messages.append("exception"),
        )

    monkeypatch.setattr(
        discovery,
        "logging",
        types.SimpleNamespace(getLogger=fake_get_logger),
    )

    monkeypatch.setattr(crawler_discovery, "NewsDiscovery", FakeDiscovery)

    args = _make_args(
        existing_article_limit=15,
        max_articles=40,
        days_back=6,
    )

    exit_code = discovery.handle_discovery_command(args)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert telemetry_calls == {
        "listed": 1,
        "summary_ids": ["op-123"],
    }
    assert "=== Failure Analysis ===" in out
    assert "Total site failures: 3" in out
    assert "Most common failure type: timeout" in out
    assert "http_error" in out
    assert captured["run"]["existing_article_limit"] == 15


def test_handle_discovery_command_handles_exception(monkeypatch, capsys):
    class FakeDiscovery:
        def __init__(self, *_a, **_k):
            self.telemetry = types.SimpleNamespace()

        def run_discovery(self, **kwargs):
            raise RuntimeError("boom")

    log_messages = {"info": [], "exception": []}

    def fake_get_logger(*_a, **_k):
        return types.SimpleNamespace(
            info=lambda message: log_messages["info"].append(message),
            exception=lambda message: log_messages["exception"].append(message),
        )

    monkeypatch.setattr(
        discovery,
        "logging",
        types.SimpleNamespace(getLogger=fake_get_logger),
    )

    monkeypatch.setattr(crawler_discovery, "NewsDiscovery", FakeDiscovery)

    args = _make_args()

    exit_code = discovery.handle_discovery_command(args)
    out = capsys.readouterr().out

    assert exit_code == 1
    assert log_messages["exception"]
    assert "Discovery command failed: boom" in out
