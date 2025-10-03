"""Discovery command for the modular CLI."""

import argparse
import logging


def add_discovery_parser(subparsers) -> argparse.ArgumentParser:
    """Add discovery command parser to subparsers."""
    discover_parser = subparsers.add_parser(
        "discover-urls",
        help="Discover article URLs using newspaper4k and StorySniffer",
    )

    discover_parser.add_argument(
        "--dataset",
        type=str,
        help="Dataset label to filter sources and tag telemetry",
    )

    discover_parser.add_argument(
        "--source-limit",
        type=int,
        help="Maximum number of sources to process",
    )

    discover_parser.add_argument(
        "--source-filter",
        type=str,
        help="Filter sources by name or URL substring",
    )

    discover_parser.add_argument(
        "--source",
        dest="source_filter",
        type=str,
        help="Alias for --source-filter (process matching source)",
    )

    discover_parser.add_argument(
        "--host",
        type=str,
        help="Filter to sources with a matching host",
    )

    discover_parser.add_argument(
        "--city",
        type=str,
        help="Filter to sources in a specific city",
    )

    discover_parser.add_argument(
        "--county",
        type=str,
        help="Filter to sources in a specific county",
    )

    discover_parser.add_argument(
        "--source-uuid",
        type=str,
        help="Process a specific source by UUID",
    )

    discover_parser.add_argument(
        "--source-uuids",
        nargs="+",
        help="Process multiple sources by UUID",
    )

    discover_parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Maximum number of articles to discover per source (default: 50)",
    )

    discover_parser.add_argument(
        "--article-limit",
        dest="legacy_article_limit",
        type=int,
        help=(
            "Legacy alias for --max-articles. When provided, also skips "
            "sources that already have this many extracted articles."
        ),
    )

    discover_parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="How many days back to look for recent articles (default: 7)",
    )

    discover_parser.add_argument(
        "--due-only",
        action="store_true",
        default=True,
        help=(
            "Only process sources due for discovery based on scheduling (default: True)"
        ),
    )

    discover_parser.add_argument(
        "--force-all",
        action="store_true",
        help=("Process all sources regardless of scheduling (disables due-only)"),
    )

    discover_parser.add_argument(
        "--host-limit",
        type=int,
        help="Maximum number of unique hosts to process",
    )

    discover_parser.add_argument(
        "--existing-article-limit",
        type=int,
        help=("Skip sources that already have at least this many extracted articles"),
    )

    discover_parser.set_defaults(func=handle_discovery_command)
    return discover_parser


def _collect_source_uuids(
    source_uuid: str | None,
    source_uuids: list[str] | None,
) -> list[str]:
    uuids: list[str] = []
    if source_uuid:
        uuids.append(source_uuid)
    if source_uuids:
        uuids.extend(source_uuids)
    return uuids


def handle_discovery_command(args) -> int:
    """Handle the discovery command using NewsDiscovery."""
    logger = logging.getLogger(__name__)

    try:
        from src.crawler.discovery import NewsDiscovery

        logger.info("Starting URL discovery pipeline")

        uuid_list = _collect_source_uuids(
            getattr(args, "source_uuid", None),
            getattr(args, "source_uuids", None),
        )

        legacy_article_limit = getattr(args, "legacy_article_limit", None)
        max_articles = getattr(args, "max_articles", 50)
        if legacy_article_limit is not None:
            max_articles = legacy_article_limit

        discovery = NewsDiscovery(
            max_articles_per_source=max_articles,
            days_back=getattr(args, "days_back", 7),
        )

        existing_article_limit = getattr(args, "existing_article_limit", None)
        if existing_article_limit is None and legacy_article_limit is not None:
            existing_article_limit = legacy_article_limit

        due_only_enabled = getattr(args, "due_only", True) and not getattr(
            args, "force_all", False
        )

        stats = discovery.run_discovery(
            dataset_label=getattr(args, "dataset", None),
            source_limit=getattr(args, "source_limit", None),
            source_filter=getattr(args, "source_filter", None),
            source_uuids=uuid_list or None,
            due_only=due_only_enabled,
            host_filter=getattr(args, "host", None),
            city_filter=getattr(args, "city", None),
            county_filter=getattr(args, "county", None),
            host_limit=getattr(args, "host_limit", None),
            existing_article_limit=existing_article_limit,
        )

        print("\n=== Discovery Results ===")
        if "sources_available" in stats:
            print(f"Sources available: {stats['sources_available']}")
            print(f"Sources due for discovery: {stats['sources_due']}")
            if stats.get("sources_skipped", 0) > 0:
                print(f"Sources skipped (not due): {stats['sources_skipped']}")

        print(f"Sources processed: {stats['sources_processed']}")
        print(f"Sources succeeded: {stats['sources_succeeded']}")
        print(f"Sources failed: {stats['sources_failed']}")

        if "sources_with_content" in stats:
            print(f"Sources with content: {stats['sources_with_content']}")
            print(f"Sources with no content: {stats['sources_no_content']}")

        print(
            f"Total candidate URLs discovered: {stats['total_candidates_discovered']}"
        )

        if stats["sources_processed"] > 0:
            technical_success_rate = (
                stats["sources_succeeded"] / stats["sources_processed"]
            ) * 100
            avg_candidates = (
                stats["total_candidates_discovered"] / stats["sources_processed"]
            )
            print(f"Technical success rate: {technical_success_rate:.1f}%")

            if "sources_with_content" in stats:
                content_success_rate = (
                    stats["sources_with_content"] / stats["sources_processed"]
                ) * 100
                print(f"Content success rate: {content_success_rate:.1f}%")

            print(f"Average candidates per source: {avg_candidates:.1f}")

        if stats["sources_failed"] > 0:
            active_ops = discovery.telemetry.list_active_operations()
            if active_ops:
                recent_op_id = active_ops[-1].get("operation_id")
                if recent_op_id:
                    failure_summary = discovery.telemetry.get_failure_summary(
                        recent_op_id
                    )
                    if failure_summary.get("total_failures", 0) > 0:
                        print("\n=== Failure Analysis ===")
                        print(
                            f"Total site failures: {failure_summary['total_failures']}"
                        )
                        most_common = failure_summary.get(
                            "most_common_failure",
                            "Unknown",
                        )
                        print(f"Most common failure type: {most_common}")
                        print("\nFailure breakdown:")
                        for failure_type, count in failure_summary[
                            "failure_types"
                        ].items():
                            percentage = (
                                count / failure_summary["total_failures"]
                            ) * 100
                            print(f"  {failure_type}: {count} ({percentage:.1f}%)")

        return 0

    except Exception as exc:
        logger.exception("Discovery command failed")
        print(f"Discovery command failed: {exc}")
        return 1
