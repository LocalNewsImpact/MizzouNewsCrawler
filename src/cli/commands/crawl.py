"""Deprecated crawl command that forwards to discover-urls."""

from __future__ import annotations

import argparse
import logging

from argparse import Namespace

from .discovery import handle_discovery_command


logger = logging.getLogger(__name__)


def add_crawl_parser(subparsers) -> argparse.ArgumentParser:
    """Register the deprecated crawl command."""
    parser = subparsers.add_parser(
        "crawl",
        help="(deprecated) Use discover-urls instead",
    )
    parser.add_argument(
        "--filter",
        required=True,
        choices=["ALL", "HOST", "COUNTY", "CITY"],
        help="Legacy filter type; forwarded to discover-urls",
    )
    parser.add_argument("--host", help="Host name for HOST filter")
    parser.add_argument("--county", help="County name for COUNTY filter")
    parser.add_argument("--city", help="City name for CITY filter")
    parser.add_argument(
        "--host-limit",
        type=int,
        help="Maximum number of hosts to process",
    )
    parser.add_argument(
        "--article-limit",
        type=int,
        help=(
            "Legacy per-host article limit; forwarded to discover-urls as "
            "--max-articles and existing-article limit"
        ),
    )
    return parser


def handle_crawl_command(args) -> int:
    """Warn and forward the crawl command to discover-urls."""
    if args.filter == "HOST" and not args.host:
        logger.error("--host required when using HOST filter")
        return 1
    if args.filter == "COUNTY" and not args.county:
        logger.error("--county required when using COUNTY filter")
        return 1
    if args.filter == "CITY" and not args.city:
        logger.error("--city required when using CITY filter")
        return 1

    logger.warning(
        "'crawl' is deprecated and will be removed. Forwarding to "
        "'discover-urls'."
    )
    print(
        "⚠️  The 'crawl' command is deprecated. Please migrate to "
        "'discover-urls'.",
    )

    legacy_limit = getattr(args, "article_limit", None)
    host_limit = getattr(args, "host_limit", None)

    mapped_args = Namespace(
        command="discover-urls",
        dataset=None,
        source_limit=host_limit,
        source_filter=None,
        source=None,
        source_uuid=None,
        source_uuids=None,
        max_articles=legacy_limit or 50,
        legacy_article_limit=legacy_limit,
        days_back=7,
        due_only=False,
        force_all=True,
        host=args.host if args.filter == "HOST" else None,
        city=args.city if args.filter == "CITY" else None,
        county=args.county if args.filter == "COUNTY" else None,
        host_limit=host_limit,
        existing_article_limit=legacy_limit,
    )

    # Ensure discover-urls sees the legacy filter for backwards compatibility
    if args.filter == "ALL":
        mapped_args.force_all = True
    elif args.filter == "HOST" and args.host:
        mapped_args.force_all = True
    elif args.filter in {"CITY", "COUNTY"}:
        mapped_args.force_all = True

    return handle_discovery_command(mapped_args)
