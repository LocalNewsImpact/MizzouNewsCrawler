"""List news sources registered in the database."""

from __future__ import annotations

import argparse
import json
import logging
import pandas as pd

from src.crawler.discovery import NewsDiscovery


logger = logging.getLogger(__name__)


def add_list_sources_parser(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "list-sources",
        help="List available sources with UUIDs and details",
    )
    parser.add_argument(
        "--dataset",
        help="Filter sources by dataset label",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    parser.set_defaults(func=handle_list_sources_command)
    return parser


def _format_table(sources_df: pd.DataFrame) -> None:
    print("\n=== Available Sources ===")
    print(f"Found {len(sources_df)} sources")
    print()

    for _, source in sources_df.iterrows():
        print(f"UUID: {source.get('id', 'N/A')}")
        print(f"Name: {source.get('name', 'N/A')}")
        print(f"URL:  {source.get('url', 'N/A')}")

        city_val = source.get("city")
        if (
            city_val is not None
            and pd.notna(city_val)
            and str(city_val).strip()
        ):
            print(f"City: {city_val}")

        county_val = source.get("county")
        if (
            county_val is not None
            and pd.notna(county_val)
            and str(county_val).strip()
        ):
            print(f"County: {county_val}")

        type_val = source.get("type_classification")
        if (
            type_val is not None
            and pd.notna(type_val)
            and str(type_val).strip()
        ):
            print(f"Type: {type_val}")

        print("-" * 60)


def handle_list_sources_command(args) -> int:
    logger.info("Listing sources for dataset: %s", args.dataset)

    try:
        discovery = NewsDiscovery()
        sources_df, _stats = discovery.get_sources_to_process(
            dataset_label=args.dataset,
        )
    except Exception as exc:
        logger.error("Failed to list sources: %s", exc)
        return 1

    if len(sources_df) == 0:
        print("No sources found.")
        return 0

    if args.format == "json":
        sources_list = sources_df.to_dict("records")
        print(json.dumps(sources_list, indent=2, default=str))
    elif args.format == "csv":
        print(sources_df.to_csv(index=False))
    else:
        _format_table(sources_df)

    logger.info("Listed %s sources", len(sources_df))
    return 0
