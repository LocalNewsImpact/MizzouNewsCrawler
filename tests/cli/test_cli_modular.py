import sys

import pytest

from src.cli import cli_modular


def _install_add_stubs(
    monkeypatch,
    *,
    with_defaults=False,
    handler_value=None,
):
    """Replace add_* parser helpers with minimal stubs for testing."""

    commands = {
        "add_verification_parser": "verify-urls",
        "add_discovery_parser": "discover-urls",
        "add_extraction_parser": "extract",
        "add_load_sources_parser": "load-sources",
        "add_list_sources_parser": "list-sources",
        "add_crawl_parser": "crawl",
        "add_discovery_report_parser": "discovery-report",
        "add_http_status_parser": "dump-http-status",
        "add_telemetry_parser": "telemetry",
        "add_status_parser": "status",
        "add_queue_parser": "queue",
    }

    def make_stub(command_name):
        def stub(subparsers):
            parser = subparsers.add_parser(command_name)
            if with_defaults:
                parser.set_defaults(
                    func=lambda args, value=handler_value: value,
                )
            return parser

        return stub

    for attr, command_name in commands.items():
        monkeypatch.setattr(cli_modular, attr, make_stub(command_name))


def test_cli_modular_main_uses_default_func(monkeypatch):
    sentinel = object()
    _install_add_stubs(monkeypatch, with_defaults=True, handler_value=sentinel)

    monkeypatch.setattr(sys, "argv", ["prog", "discover-urls"])

    result = cli_modular.main()

    assert result is sentinel


def test_cli_modular_main_routes_without_default(monkeypatch):
    _install_add_stubs(monkeypatch, with_defaults=False)

    calls = {}

    def fake_discovery_handler(args):
        calls["discovery"] = args.command
        return 42

    monkeypatch.setattr(
        cli_modular,
        "handle_discovery_command",
        fake_discovery_handler,
    )

    monkeypatch.setattr(sys, "argv", ["prog", "discover-urls"])

    result = cli_modular.main()

    assert result == 42
    assert calls["discovery"] == "discover-urls"


def test_cli_modular_unknown_command(monkeypatch, capsys):
    _install_add_stubs(monkeypatch, with_defaults=False)

    monkeypatch.setattr(sys, "argv", ["prog", "unknown"])

    with pytest.raises(SystemExit) as excinfo:
        cli_modular.main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr().err
    assert "invalid choice" in captured


def test_cli_modular_routes_all_supported_commands(monkeypatch):
    _install_add_stubs(monkeypatch, with_defaults=False)

    command_to_handler = {
        "verify-urls": "handle_verification_command",
        "discover-urls": "handle_discovery_command",
        "extract": "handle_extraction_command",
        "load-sources": "handle_load_sources_command",
        "list-sources": "handle_list_sources_command",
        "crawl": "handle_crawl_command",
        "discovery-report": "handle_discovery_report_command",
        "queue": "handle_queue_command",
        "status": "handle_status_command",
        "dump-http-status": "handle_http_status_command",
    }

    for command, handler_attr in command_to_handler.items():
        called = {}

        def handler(args, command=command, called=called):
            called["command"] = getattr(args, "command", None)
            return f"handled-{command}"

        monkeypatch.setattr(cli_modular, handler_attr, handler)
        monkeypatch.setattr(sys, "argv", ["prog", command])

        result = cli_modular.main()

        assert result == f"handled-{command}"
        assert called["command"] == command
