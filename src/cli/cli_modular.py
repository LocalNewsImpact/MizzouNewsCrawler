"""Streamlined CLI interface with modular command structure."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path

# typing imports intentionally omitted; use inline type-ignore where necessary

# ALL command modules are now lazy-loaded - nothing imported at module level
# This makes CLI startup instant (~0.1s instead of ~15s with spacy/ML imports)
# Commands are imported on-demand in _load_command_parser()

logger = logging.getLogger(__name__)

# Ensure project root is discoverable when invoked via ``python -m``
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


CommandHandler = Callable[[argparse.Namespace], int]

COMMAND_HANDLER_ATTRS: dict[str, str] = {
    "verify-urls": "handle_verification_command",
    "discover-urls": "handle_discovery_command",
    "discovery-status": "handle_discovery_status_command",
    "extract": "handle_extraction_command",
    "extract-entities": "handle_entity_extraction_command",
    "clean-articles": "handle_cleaning_command",
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
    "pipeline-status": "handle_pipeline_status_command",
}


def create_parser() -> argparse.ArgumentParser:
    """Create minimal parser - commands loaded on-demand in main()."""
    parser = argparse.ArgumentParser(
        prog="news-crawler",
        description="MizzouNewsCrawler - News discovery and verification",
        add_help=False,  # We'll handle help per-command
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (e.g. INFO, DEBUG)",
    )

    # Just capture the command name, don't load subparsers yet
    parser.add_argument(
        "command",
        nargs="?",
        help="Command to run (use 'COMMAND --help' for command-specific help)",
    )

    return parser


def _load_command_parser(command: str) -> tuple[Callable, Callable] | None:
    """Load parser and handler for a specific command on-demand.

    Returns: (add_parser_func, handle_command_func) or None if not found
    """
    command_modules = {
        "verify-urls": "verification",
        "discover-urls": "discovery",
        "discovery-status": "discovery_status",
        "extract": "extraction",
        "extract-entities": "entity_extraction",
        "clean-articles": "cleaning",
        "analyze": "analysis",
        "load-sources": "load_sources",
        "list-sources": "list_sources",
        "crawl": "crawl",
        "discovery-report": "discovery_report",
        "telemetry": "telemetry",
        "county-report": "reports",
        "populate-gazetteer": "gazetteer",
        "create-version": "versioning",
        "list-versions": "versioning",
        "export-version": "versioning",
        "export-snapshot": "versioning",
        "status": "background_processes",
        "queue": "background_processes",
        "dump-http-status": "http_status",
        "llm": "llm",
        "pipeline-status": "pipeline_status",
    }

    module_name = command_modules.get(command)
    if not module_name:
        return None

    try:
        # Dynamic import of just the needed command module
        module = __import__(
            f"src.cli.commands.{module_name}",
            fromlist=["*"],
        )

        # Get the parser and handler functions
        parser_func = None
        handler_func = None

        # Try to find add_*_parser function
        for attr in dir(module):
            if attr.startswith("add_") and attr.endswith("_parser"):
                parser_func = getattr(module, attr)
                break

        # Try to find handle_*_command function
        for attr in dir(module):
            if attr.startswith("handle_") and attr.endswith("_command"):
                handler_func = getattr(module, attr)
                break

        if parser_func and handler_func:
            return (parser_func, handler_func)

    except (ImportError, ModuleNotFoundError) as e:
        logger.warning(f"Failed to load command '{command}': {e}")
        return None

    return None


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
        # func is already a callable with the correct runtime signature
        return func  # type: ignore[return-value]

    if command is None:
        return None

    attr_name = COMMAND_HANDLER_ATTRS.get(command)
    if not attr_name:
        return None

    handler = globals().get(attr_name)
    if callable(handler):
        return handler  # type: ignore[return-value]

    # Lazy load extraction handler to avoid slow spacy import (~14s)
    if command == "extract" and attr_name == "handle_extraction_command":
        try:
            from .commands.extraction import handle_extraction_command

            return handle_extraction_command  # type: ignore[return-value]
        except (ImportError, ModuleNotFoundError):
            return None  # spacy not available

    # Lazy load entity extraction handler - avoid slow spacy (~14s)
    if (
        command == "extract-entities"
        and attr_name == "handle_entity_extraction_command"
    ):
        try:
            from .commands.entity_extraction import (
                handle_entity_extraction_command,
            )

            return handle_entity_extraction_command  # type: ignore[return-value]
        except (ImportError, ModuleNotFoundError):
            return None  # spacy not available

    # Lazy load analysis handler if ML dependencies are available
    if command == "analyze" and attr_name == "handle_analysis_command":
        try:
            from .commands.analysis import handle_analysis_command

            return handle_analysis_command  # type: ignore[return-value]
        except (ImportError, ModuleNotFoundError):
            return None  # ML dependencies not available

    return None


def main(
    argv: list[str] | None = None,
    *,
    setup_logging_func: Callable[[str], None] | None = None,
    handler_overrides: dict[str, CommandHandler] | None = None,
) -> int:
    """Main CLI entry point with on-demand command loading."""

    # Parse just enough to get command and log level
    parser = create_parser()
    args, remaining = parser.parse_known_args(argv)

    log_level = getattr(args, "log_level", "INFO") or "INFO"
    if setup_logging_func is None:
        from .context import setup_logging as default_setup_logging

        setup_logging_func = default_setup_logging

    setup_logging_func(log_level)

    command = args.command
    if not command:
        print("Available commands:", file=sys.stderr)
        print("  pipeline-status  - Show pipeline status")
        print("  discover-urls    - Discover URLs from news sources")
        print("  verify-urls      - Verify discovered URLs")
        print("  extract          - Extract article content")
        print("  analyze          - Analyze articles with ML")
        print("  status           - Show background process status")
        print("Use: news-crawler COMMAND --help for more info")
        return 1

    # Check for overrides first
    if handler_overrides and command in handler_overrides:
        handler = handler_overrides[command]
        # Re-parse with full args
        full_parser = argparse.ArgumentParser()
        full_parser.add_argument("command")
        full_args = full_parser.parse_args(argv)
        return handler(full_args)

    # Load the specific command module on-demand
    result = _load_command_parser(command)
    if result is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1

    add_parser_func, handle_func = result

    # Create a new parser with the specific command
    full_parser = argparse.ArgumentParser(
        prog=f"news-crawler {command}",
        description=f"Run {command} command",
    )
    full_parser.add_argument("--log-level", default="INFO")

    # Let the command add its own arguments
    subparsers = full_parser.add_subparsers(dest="command")
    add_parser_func(subparsers)

    # Re-parse with the command-specific parser
    full_args = full_parser.parse_args([command] + remaining)

    # Run the command handler
    return handle_func(full_args)


if __name__ == "__main__":
    sys.exit(main())
