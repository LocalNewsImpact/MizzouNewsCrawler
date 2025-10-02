"""Reporting-oriented commands for the modular CLI."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from src.reporting.county_report import (
    CountyReportConfig,
    generate_county_report,
)

logger = logging.getLogger(__name__)


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - argument parsing
        raise argparse.ArgumentTypeError(
            "Dates must be in ISO format, e.g. 2024-09-01 or 2024-09-01T12:00"
        ) from exc


def add_reports_parser(subparsers) -> argparse.ArgumentParser:
    """Register the report-related commands."""

    parser = subparsers.add_parser(
        "county-report",
        help="Generate a county-filtered article CSV report",
    )
    parser.add_argument(
        "--counties",
        nargs="+",
        required=True,
        metavar="COUNTY",
        help="One or more county names to include in the report.",
    )
    parser.add_argument(
        "--start-date",
        type=_parse_datetime,
        required=True,
        help="Earliest publication date to include (ISO format)",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_datetime,
        help="Optional latest publication date (ISO format)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Destination CSV path. Defaults to " "reports/county_report_<timestamp>.csv"
        ),
    )
    parser.add_argument(
        "--db-url",
        default="sqlite:///data/mizzou.db",
        help="Database URL to query (default: sqlite:///data/mizzou.db)",
    )
    parser.add_argument(
        "--label-version",
        help="Restrict labels to a specific version (optional)",
    )
    parser.add_argument(
        "--entity-separator",
        default="; ",
        help="Separator to use when joining entity strings (default: '; ')",
    )
    parser.add_argument(
        "--no-entities",
        action="store_true",
        help="Exclude aggregated entities column from the output",
    )
    parser.set_defaults(func=handle_county_report_command)
    return parser


def handle_county_report_command(args) -> int:
    """Execute the county-report command."""

    include_entities = not getattr(args, "no_entities", False)

    output_path: Path | None = getattr(args, "output", None)
    if output_path is None:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = Path("reports") / f"county_report_{timestamp}.csv"

    config = CountyReportConfig(
        counties=list(args.counties),
        start_date=args.start_date,
        end_date=getattr(args, "end_date", None),
        database_url=getattr(args, "db_url", "sqlite:///data/mizzou.db"),
        include_entities=include_entities,
        entity_separator=getattr(args, "entity_separator", "; "),
        label_version=getattr(args, "label_version", None),
    )

    try:
        df = generate_county_report(config, output_path=output_path)
    except Exception as exc:  # pragma: no cover - passthrough logging
        logger.exception("Failed to generate county report")
        print(f"County report failed: {exc}")
        return 1

    print(f"Wrote {len(df)} rows to {output_path}")
    return 0
