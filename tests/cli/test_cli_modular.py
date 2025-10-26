import sys

from src.cli import cli_modular


def _install_add_stubs(
    monkeypatch,
    *,
    with_defaults=False,
    handler_value=None,
):
    """Replace _load_command_parser with a stub for testing."""

    def make_stub_loader(command_name):
        def add_parser_stub(subparsers):
            parser = subparsers.add_parser(command_name)
            if with_defaults:
                parser.set_defaults(
                    func=lambda args, value=handler_value: value,
                )
            return parser

        def handler_stub(args):
            return handler_value

        return (add_parser_stub, handler_stub)

    def stub_load_command_parser(command):
        # Return stub parser and handler for any command
        return make_stub_loader(command)

    monkeypatch.setattr(cli_modular, "_load_command_parser", stub_load_command_parser)


def test_cli_modular_main_uses_default_func(monkeypatch):
    sentinel = object()
    _install_add_stubs(monkeypatch, with_defaults=True, handler_value=sentinel)

    monkeypatch.setattr(sys, "argv", ["prog", "discover-urls"])

    result = cli_modular.main()

    assert result is sentinel


def test_cli_modular_main_routes_without_default(monkeypatch):
    calls = {}

    def fake_discovery_handler(args):
        calls["discovery"] = args.command
        return 42

    def stub_add_parser(subparsers):
        parser = subparsers.add_parser("discover-urls")
        return parser

    def stub_load_command_parser(command):
        if command == "discover-urls":
            return (stub_add_parser, fake_discovery_handler)
        return None

    monkeypatch.setattr(cli_modular, "_load_command_parser", stub_load_command_parser)
    monkeypatch.setattr(sys, "argv", ["prog", "discover-urls"])

    result = cli_modular.main()

    assert result == 42
    assert calls["discovery"] == "discover-urls"


def test_cli_modular_unknown_command(monkeypatch, capsys):
    # Stub that returns None for unknown commands
    def stub_load_command_parser(command):
        return None  # Unknown command

    monkeypatch.setattr(cli_modular, "_load_command_parser", stub_load_command_parser)
    monkeypatch.setattr(sys, "argv", ["prog", "unknown"])

    result = cli_modular.main()

    assert result == 1  # Error code for unknown command
    captured = capsys.readouterr().err
    assert "Unknown command" in captured


def test_cli_modular_routes_all_supported_commands(monkeypatch):
    commands = [
        "verify-urls",
        "discover-urls",
        "extract",
        "load-sources",
        "list-sources",
        "crawl",
        "discovery-report",
        "queue",
        "status",
        "dump-http-status",
    ]

    for command in commands:
        called = {}

        def handler(args, command=command, called=called):
            called["command"] = getattr(args, "command", None)
            return f"handled-{command}"

        def stub_add_parser(subparsers, cmd=command):
            parser = subparsers.add_parser(cmd)
            return parser

        def stub_load_command_parser(cmd, handler=handler, stub_add=stub_add_parser):
            if cmd == command:
                return (stub_add, handler)
            return None

        monkeypatch.setattr(
            cli_modular, "_load_command_parser", stub_load_command_parser
        )
        monkeypatch.setattr(sys, "argv", ["prog", command])

        result = cli_modular.main()

        assert result == f"handled-{command}"
        assert called["command"] == command
