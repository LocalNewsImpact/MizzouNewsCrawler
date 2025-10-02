import json
from types import SimpleNamespace

import pandas as pd

import src.cli.commands.list_sources as list_sources


class DummyLogger:
    def __init__(self):
        self.info_calls = []
        self.error_calls = []

    def info(self, message, *args):
        if args:
            message = message % args
        self.info_calls.append(message)

    def error(self, message, *args):
        if args:
            message = message % args
        self.error_calls.append(message)


def _fake_discovery(df, *, dataset_capture):
    class FakeDiscovery:
        def __init__(self):
            dataset_capture.clear()

        def get_sources_to_process(self, dataset_label):
            dataset_capture["dataset"] = dataset_label
            return df, {"count": len(df)}

    return FakeDiscovery()


def test_handle_list_sources_json(monkeypatch, capsys):
    df = pd.DataFrame(
        [
            {"id": "id-1", "name": "Source 1", "url": "https://one"},
            {"id": "id-2", "name": "Source 2", "url": "https://two"},
        ]
    )
    captured = {}
    monkeypatch.setattr(
        list_sources,
        "NewsDiscovery",
        lambda: _fake_discovery(df, dataset_capture=captured),
    )

    args = SimpleNamespace(dataset="test-dataset", format="json")

    exit_code = list_sources.handle_list_sources_command(args)

    assert exit_code == 0
    assert captured["dataset"] == "test-dataset"

    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2
    assert data[0]["id"] == "id-1"


def test_handle_list_sources_csv(monkeypatch, capsys):
    df = pd.DataFrame([{"id": "id-1", "name": "Source 1", "url": "https://one"}])
    monkeypatch.setattr(
        list_sources,
        "NewsDiscovery",
        lambda: _fake_discovery(df, dataset_capture={}),
    )

    args = SimpleNamespace(dataset=None, format="csv")

    exit_code = list_sources.handle_list_sources_command(args)

    assert exit_code == 0
    output = capsys.readouterr().out.strip()
    assert output.splitlines()[0] == "id,name,url"
    assert "https://one" in output


def test_handle_list_sources_table(monkeypatch, capsys):
    df = pd.DataFrame(
        [
            {
                "id": "a",
                "name": "Alpha",
                "url": "https://alpha",
                "city": "Columbia",
                "county": "Boone",
                "type_classification": "Daily",
            },
            {
                "id": "b",
                "name": "Beta",
                "url": "https://beta",
                "city": None,
                "county": " ",
                "type_classification": float("nan"),
            },
        ]
    )
    monkeypatch.setattr(
        list_sources,
        "NewsDiscovery",
        lambda: _fake_discovery(df, dataset_capture={}),
    )

    args = SimpleNamespace(dataset="test", format="table")

    exit_code = list_sources.handle_list_sources_command(args)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "=== Available Sources ===" in output
    assert "City: Columbia" in output
    assert "County: Boone" in output
    assert "Type: Daily" in output
    assert output.count("UUID:") == 2


def test_handle_list_sources_handles_errors(monkeypatch):
    class FailingDiscovery:
        def __init__(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(list_sources, "NewsDiscovery", FailingDiscovery)
    logger = DummyLogger()
    monkeypatch.setattr(list_sources, "logger", logger)

    args = SimpleNamespace(dataset="err", format="table")

    exit_code = list_sources.handle_list_sources_command(args)

    assert exit_code == 1
    assert logger.error_calls
    assert "Failed to list sources" in logger.error_calls[0]


def test_handle_list_sources_no_results(monkeypatch, capsys):
    empty_df = pd.DataFrame(columns=["id", "name", "url"])
    monkeypatch.setattr(
        list_sources,
        "NewsDiscovery",
        lambda: _fake_discovery(empty_df, dataset_capture={}),
    )

    args = SimpleNamespace(dataset=None, format="json")

    exit_code = list_sources.handle_list_sources_command(args)

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "No sources found."
