"""One-off smoke test runner: run discovery for a single source and print candidate links.

This script is temporary and intended for local verification only. It will not
modify the `sources` table. It uses `NewsDiscovery.process_source` logic but
runs in a minimal way to avoid modifying the database other than reading.

Usage:
    python scripts/smoke_discover.py <host>

Example:
    python scripts/smoke_discover.py npr.org
"""

import json
import logging
import sys

from src.crawler.discovery import NewsDiscovery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main(host: str):
    nd = NewsDiscovery()
    # Build a fake source_row similar to get_sources_to_process output
    # Only include fields that process_source expects: id, name, url, metadata, host
    source_row = {
        "id": None,
        "name": host,
        "url": f"https://{host}",
        "metadata": json.dumps({}),
        "host": host,
    }

    # We call discover_with_rss_feeds directly to avoid DB writes
    articles = nd.discover_with_rss_feeds(
        source_url=source_row["url"], custom_rss_feeds=None
    )

    print(f"Discovered {len(articles)} candidate URLs for {host}")
    for a in articles:
        label = nd._format_discovered_by(a)
        print(label, a.get("url"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/smoke_discover.py <host>")
        sys.exit(1)
    main(sys.argv[1])
