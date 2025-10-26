"""Generate discovery outcomes reports for the modular CLI."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def add_discovery_report_parser(subparsers) -> argparse.ArgumentParser:
    """Register the discovery-report command."""
    parser = subparsers.add_parser(
        "discovery-report",
        help="Generate detailed discovery outcomes report",
    )
    parser.add_argument(
        "--operation-id",
        type=str,
        help="Show report for a specific discovery operation ID",
    )
    parser.add_argument(
        "--hours-back",
        type=int,
        default=24,
        help=("Hours back to analyze when no operation is provided (default: 24)"),
    )
    parser.add_argument(
        "--format",
        choices=["summary", "detailed", "json"],
        default="summary",
        help="Report format (default: summary)",
    )
    parser.set_defaults(func=handle_discovery_report_command)
    return parser


def handle_discovery_report_command(args) -> int:
    """Execute the discovery-report command."""
    try:
        from src.crawler.discovery import NewsDiscovery

        discovery = NewsDiscovery()
        report = discovery.telemetry.get_discovery_outcomes_report(
            operation_id=getattr(args, "operation_id", None),
            hours_back=getattr(args, "hours_back", 24),
        )

        if "error" in report:
            print(f"Error generating report: {report['error']}")
            return 1

        if getattr(args, "format", "summary") == "json":
            print(json.dumps(report, indent=2, default=str))
            return 0

        if getattr(args, "format", "summary") == "detailed":
            _print_detailed_discovery_report(report)
        else:
            _print_summary_discovery_report(report)

        return 0
    except Exception as exc:  # pragma: no cover - passthrough logging
        logger.exception("Discovery report command failed")
        print(f"Discovery report failed: {exc}")
        return 1


def _print_summary_discovery_report(report: dict[str, Any]) -> None:
    """Print a summary view of the discovery report."""
    summary = report.get("summary", {})

    print("\n=== Discovery Outcomes Summary ===")
    print(f"Total sources processed: {summary.get('total_sources', 0)}")
    print(f"Technical success rate: {summary.get('technical_success_rate', 0)}%")
    print(f"Content success rate: {summary.get('content_success_rate', 0)}%")
    print(f"New articles found: {summary.get('total_new_articles', 0)}")
    avg_time = summary.get("avg_discovery_time_ms")
    if avg_time is not None:
        print(f"Average discovery time: {float(avg_time):.1f}ms")

    print("\n=== Outcome Breakdown ===")
    for outcome in report.get("outcome_breakdown", []):
        outcome_name = outcome.get("outcome", "Unknown")
        count = outcome.get("count", 0)
        percentage = outcome.get("percentage", 0)
        print(f"  {outcome_name}: {count} ({percentage}%)")

    top_sources = report.get("top_performing_sources", [])
    if top_sources:
        print("\n=== Top Performing Sources ===")
        for source in top_sources[:5]:
            name = source.get("source_name", "Unknown")
            rate = source.get("content_success_rate", 0)
            articles = source.get("total_new_articles", 0)
            print(f"  {name}: {rate}% success, {articles} articles")


def _print_detailed_discovery_report(report: dict[str, Any]) -> None:
    """Print a detailed view of the discovery report."""
    _print_summary_discovery_report(report)

    summary = report.get("summary", {})
    print("\n=== Detailed Statistics ===")
    print(f"Technical successes: {summary.get('technical_success_count', 0)}")
    print(f"Content successes: {summary.get('content_success_count', 0)}")
    print(f"Technical failures: {summary.get('technical_failure_count', 0)}")
    print(f"Total articles found: {summary.get('total_articles_found', 0)}")
    print(f"Duplicate articles: {summary.get('total_duplicate_articles', 0)}")
    print(f"Expired articles: {summary.get('total_expired_articles', 0)}")

    top_sources = report.get("top_performing_sources", [])
    if not top_sources:
        return

    print("\n=== All Performing Sources ===")
    for source in top_sources:
        name = source.get("source_name", "Unknown")
        attempts = source.get("attempts", 0)
        content_successes = source.get("content_successes", 0)
        rate = source.get("content_success_rate", 0)
        articles = source.get("total_new_articles", 0)
        print(f"  {name}:")
        print(f"    Attempts: {attempts}")
        print(f"    Content successes: {content_successes}")
        print(f"    Success rate: {rate}%")
        print(f"    Total new articles: {articles}")
