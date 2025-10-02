"""Streamlined CLI interface with modular command structure."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from .commands.analysis import (  # noqa: F401
    add_analysis_parser,
    handle_analysis_command,
)
from .commands.background_processes import (  # noqa: F401
    add_queue_parser,
    add_status_parser,
    handle_queue_command,
    handle_status_command,
)
from .commands.crawl import handle_crawl_command  # noqa: F401
from .commands.crawl import (
    add_crawl_parser,
)
from .commands.discovery import (  # noqa: F401
    add_discovery_parser,
    handle_discovery_command,
)
from .commands.discovery_report import (  # noqa: F401
    add_discovery_report_parser,
    handle_discovery_report_command,
)
from .commands.extraction import (  # noqa: F401
    add_extraction_parser,
    handle_extraction_command,
)
from .commands.gazetteer import handle_gazetteer_command  # noqa: F401
from .commands.gazetteer import (
    add_gazetteer_parser,
)
from .commands.http_status import (  # noqa: F401
    add_http_status_parser,
    handle_http_status_command,
)
from .commands.list_sources import (  # noqa: F401
    add_list_sources_parser,
    handle_list_sources_command,
)
from .commands.llm import handle_llm_command  # noqa: F401
from .commands.llm import (
    add_llm_parser,
)
from .commands.load_sources import (  # noqa: F401
    add_load_sources_parser,
    handle_load_sources_command,
)
from .commands.reports import (  # noqa: F401
    add_reports_parser,
    handle_county_report_command,
)
from .commands.telemetry import (  # noqa: F401
    add_telemetry_parser,
    handle_telemetry_command,
)
from .commands.verification import (  # noqa: F401
    add_verification_parser,
    handle_verification_command,
)
from .commands.versioning import (  # noqa: F401
    add_versioning_parsers,
    handle_create_version_command,
    handle_export_snapshot_command,
    handle_export_version_command,
    handle_list_versions_command,
)

# Ensure project root is discoverable when invoked via ``python -m``
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


CommandHandler = Callable[[argparse.Namespace], int]

COMMAND_HANDLER_ATTRS: dict[str, str] = {
    "verify-urls": "handle_verification_command",
    "discover-urls": "handle_discovery_command",
    "extract": "handle_extraction_command",
    "analyze": "handle_analysis_command",
    "load-sources": "handle_load_sources_command",
    "list-sources": "handle_list_sources_command",
    "crawl": "handle_crawl_command",
    "discovery-report": "handle_discovery_report_command",
    "telemetry": "handle_telemetry_command",
    "county-report": "handle_county_report_command",
    "populate-gazetteer": "handle_gazetteer_command",
    "create-version": "handle_create_version_command",
    "list-versions": "handle_list_versions_command",
    "export-version": "handle_export_version_command",
    "export-snapshot": "handle_export_snapshot_command",
    "status": "handle_status_command",
    "queue": "handle_queue_command",
    "dump-http-status": "handle_http_status_command",
    "llm": "handle_llm_command",
}


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="news-crawler",
        description="MizzouNewsCrawler - News discovery and verification",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (e.g. INFO, DEBUG)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=False,
    )

    add_verification_parser(subparsers)
    add_discovery_parser(subparsers)
    add_extraction_parser(subparsers)
    add_analysis_parser(subparsers)
    add_load_sources_parser(subparsers)
    add_list_sources_parser(subparsers)
    add_crawl_parser(subparsers)
    add_discovery_report_parser(subparsers)
    add_http_status_parser(subparsers)
    add_telemetry_parser(subparsers)
    add_reports_parser(subparsers)
    add_gazetteer_parser(subparsers)
    add_versioning_parsers(subparsers)
    add_status_parser(subparsers)
    add_queue_parser(subparsers)
    add_llm_parser(subparsers)

    return parser


def _resolve_handler(
    args: argparse.Namespace,
    overrides: dict[str, CommandHandler] | None = None,
) -> CommandHandler | None:
    func = getattr(args, "func", None)
    command = getattr(args, "command", None)
    if overrides and command and command in overrides:
        return overrides[command]

    func = getattr(args, "func", None)
    if callable(func):
        return cast(CommandHandler, func)

    if command is None:
        return None

    attr_name = COMMAND_HANDLER_ATTRS.get(command)
    if not attr_name:
        return None

    handler = globals().get(attr_name)
    if callable(handler):
        return cast(CommandHandler, handler)

    return None


def main(
    argv: list[str] | None = None,
    *,
    setup_logging_func: Callable[[str], None] | None = None,
    handler_overrides: dict[str, CommandHandler] | None = None,
) -> int:
    """Main CLI entry point."""

    parser = create_parser()
    args = parser.parse_args(argv)

    log_level = getattr(args, "log_level", "INFO") or "INFO"
    if setup_logging_func is None:
        from .context import setup_logging as default_setup_logging

        setup_logging_func = default_setup_logging

    setup_logging_func(log_level)

    handler = _resolve_handler(args, overrides=handler_overrides)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
