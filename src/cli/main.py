"""Deprecated legacy CLI entry point maintained for compatibility.

The modular CLI lives in :mod:`src.cli.cli_modular`. This module forwards
all invocations there while keeping historical function names importable
for callers that still reference the legacy surface.
"""

from __future__ import annotations

import warnings

from src.models.versioning import (
    create_dataset_version,
    export_dataset_version,
    export_snapshot_for_version,
    list_dataset_versions,
)

from .cli_modular import main as _modular_main

# Lazy import for analysis to avoid importing torch in crawler image
try:
    from .commands.analysis import handle_analysis_command as analyze_command
except (ImportError, ModuleNotFoundError):
    analyze_command = None  # type: ignore

from .commands.background_processes import handle_queue_command as queue_command
from .commands.background_processes import handle_status_command as status_command
from .commands.crawl import handle_crawl_command as crawl_command
from .commands.discovery import handle_discovery_command as discover_urls_command
from .commands.discovery_report import (
    handle_discovery_report_command as discovery_report_command,
)
from .commands.extraction import handle_extraction_command as extract_command
from .commands.gazetteer import handle_gazetteer_command as populate_gazetteer_command
from .commands.http_status import handle_http_status_command as dump_http_status_command
from .commands.list_sources import handle_list_sources_command as list_sources_command
from .commands.llm import handle_llm_command as llm_command
from .commands.load_sources import handle_load_sources_command as load_sources_command
from .commands.telemetry import handle_telemetry_command as telemetry_command
from .context import setup_logging

__all__ = [
    "main",
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
    "llm_command",
    "create_dataset_version",
    "export_dataset_version",
    "export_snapshot_for_version",
    "list_dataset_versions",
]


def main() -> int:
    """Forward execution to the modular CLI with a deprecation warning."""
    warnings.warn(
        "src.cli.main is deprecated; please invoke src.cli.cli_modular instead",
        category=DeprecationWarning,
        stacklevel=2,
    )
    handler_overrides = {
        "load-sources": load_sources_command,
        "list-sources": list_sources_command,
        "crawl": crawl_command,
        "extract": extract_command,
        "telemetry": telemetry_command,
        "populate-gazetteer": populate_gazetteer_command,
        "discover-urls": discover_urls_command,
        "discovery-report": discovery_report_command,
        "queue": queue_command,
        "status": status_command,
        "dump-http-status": dump_http_status_command,
        "llm": llm_command,
    }
    
    # Add analyze command if ML dependencies are available
    if analyze_command is not None:
        handler_overrides["analyze"] = analyze_command

    try:
        return _modular_main(
            setup_logging_func=setup_logging,
            handler_overrides=handler_overrides,
        )
    except TypeError:
        # Support tests or legacy call sites that patch _modular_main with a
        # simplified signature that does not accept keyword arguments.
        return _modular_main()
