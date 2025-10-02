import pytest

import src.cli.main as main
from src.cli import context as cli_context


def test_main_forwards_to_modular_cli(monkeypatch):
    sentinel = object()
    records = {}

    def fake_modular_main():
        records["called"] = True
        return sentinel

    def fake_warn(message, *args, **kwargs):
        records["warning_message"] = message
        records["warning_kwargs"] = kwargs

    monkeypatch.setattr(main, "_modular_main", fake_modular_main)
    monkeypatch.setattr(main.warnings, "warn", fake_warn)

    result = main.main()

    assert result is sentinel
    assert records.get("called") is True
    message = records["warning_message"]
    assert isinstance(message, str)
    assert message.startswith("src.cli.main is deprecated")
    warning_kwargs = records["warning_kwargs"]
    assert warning_kwargs.get("category") is DeprecationWarning


def test_main_exports_legacy_symbols():
    expected_symbols = {
        "setup_logging",
        "load_sources_command",
        "list_sources_command",
        "crawl_command",
        "extract_command",
        "telemetry_command",
        "analyze_command",
        "populate_gazetteer_command",
        "discover_urls_command",
        "discovery_report_command",
        "queue_command",
        "status_command",
        "dump_http_status_command",
        "create_dataset_version",
        "export_dataset_version",
        "export_snapshot_for_version",
        "list_dataset_versions",
    }

    missing = {name for name in expected_symbols if not hasattr(main, name)}
    assert not missing, f"Missing exports: {missing}"


@pytest.mark.requires_setup_logging
def test_setup_logging_configures_handlers(monkeypatch):
    recorded = {}
    created_handlers = []

    class DummyStreamHandler:
        def __init__(self, stream):
            created_handlers.append(("stream", stream))

    class DummyFileHandler:
        def __init__(self, filename):
            created_handlers.append(("file", filename))

    def fake_basic_config(**kwargs):
        recorded["called"] = True
        recorded["kwargs"] = kwargs

    monkeypatch.setattr(
        cli_context.logging, "StreamHandler", DummyStreamHandler
    )
    monkeypatch.setattr(cli_context.logging, "FileHandler", DummyFileHandler)
    monkeypatch.setattr(cli_context.logging, "basicConfig", fake_basic_config)

    main.setup_logging("debug")

    assert recorded.get("called") is True
    assert recorded["kwargs"]["level"] == cli_context.logging.DEBUG
    assert recorded["kwargs"]["format"].startswith("%(")
    assert len(recorded["kwargs"]["handlers"]) == 2
    assert created_handlers == [
        ("stream", cli_context.sys.stdout),
        ("file", "crawler.log"),
    ]
