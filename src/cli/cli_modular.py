"""
Streamlined CLI interface with modular command structure.

This is a refactored version of the main CLI that splits commands into
separate modules for better maintainability.
"""

import argparse
import sys
from pathlib import Path

# Import command modules
from .commands.verification import (
    add_verification_parser, handle_verification_command,
)
from .commands.discovery import (
    add_discovery_parser, handle_discovery_command,
)
from .commands.extraction import (
    add_extraction_parser, handle_extraction_command,
)
from .commands.analysis import (
    add_analysis_parser, handle_analysis_command,
)
from .commands.load_sources import (
    add_load_sources_parser, handle_load_sources_command,
)
from .commands.list_sources import (
    add_list_sources_parser, handle_list_sources_command,
)
from .commands.crawl import (
    add_crawl_parser, handle_crawl_command,
)
from .commands.discovery_report import (
    add_discovery_report_parser, handle_discovery_report_command,
)
from .commands.background_processes import (
    add_status_parser, add_queue_parser,
    handle_status_command, handle_queue_command,
)
from .commands.http_status import (
    add_http_status_parser, handle_http_status_command,
)
from .commands.telemetry import add_telemetry_parser

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="news-crawler",
        description="MizzouNewsCrawler - News discovery and verification"
    )
    
    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True
    )
    
    # Add verification commands
    add_verification_parser(subparsers)

    # Add discovery commands
    add_discovery_parser(subparsers)

    # Add extraction commands
    add_extraction_parser(subparsers)

    # Add ML analysis commands
    add_analysis_parser(subparsers)

    # Data management commands
    add_load_sources_parser(subparsers)
    add_list_sources_parser(subparsers)
    add_crawl_parser(subparsers)

    # Telemetry and reporting
    add_discovery_report_parser(subparsers)
    add_http_status_parser(subparsers)
    add_telemetry_parser(subparsers)

    # Background process monitoring
    add_status_parser(subparsers)
    add_queue_parser(subparsers)
    
    return parser


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Route to appropriate command handler
    if hasattr(args, "func"):
        return args.func(args)

    if args.command == "verify-urls":
        return handle_verification_command(args)
    elif args.command == "discover-urls":
        return handle_discovery_command(args)
    elif args.command == "extract":
        return handle_extraction_command(args)
    elif args.command == "analyze":
        return handle_analysis_command(args)
    elif args.command == "load-sources":
        return handle_load_sources_command(args)
    elif args.command == "list-sources":
        return handle_list_sources_command(args)
    elif args.command == "crawl":
        return handle_crawl_command(args)
    elif args.command == "discovery-report":
        return handle_discovery_report_command(args)
    elif args.command == "queue":
        return handle_queue_command(args)
    elif args.command == "status":
        return handle_status_command(args)
    elif args.command == "dump-http-status":
        return handle_http_status_command(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
