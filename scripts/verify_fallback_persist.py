"""Run a single discovery.process_source with a DummyDiscovery and print DB rows
that include 'fallback_include_older' in the stored `meta` column.

Usage:
    source ./venv/bin/activate
    python scripts/verify_fallback_persist.py

This script is intended to be executed in the developer's venv where all
project dependencies (sqlalchemy, feedparser, etc.) are installed.
"""

import json
import pathlib
import sys
from pprint import pprint

import pandas as pd

# Make project root importable (so `src` package resolves)
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crawler.discovery import NewsDiscovery  # noqa: E402
from src.models.database import (  # noqa: E402
    DatabaseManager,
    read_candidate_links,
)


class DummyDiscovery(NewsDiscovery):
    def discover_with_rss_feeds(
        self,
        source_url,
        source_id=None,
        operation_id=None,
        custom_rss_feeds=None,
        source_meta=None,
    ):
        # Return a single fallback article with the flag set
        articles = [
            {
                "url": "https://example.com/old-article",
                "source_url": source_url,
                "discovery_method": "rss_feed",
                "discovered_at": "2025-09-20T00:00:00",
                "title": "Old Article",
                "metadata": {
                    "rss_feed_url": "https://example.com/feed",
                    "feed_entry_count": 3,
                    "fallback_include_older": True,
                },
            }
        ]
        metadata = {"fallback_count": 1}
        return articles, metadata


def main():
    db_url = "sqlite:///data/mizzou.db"
    src_row = pd.Series(
        {
            "id": "verify-source-id",
            "name": "Verify Source",
            "url": "https://example.com",
            "metadata": json.dumps({"frequency": "monthly"}),
        }
    )

    discovery = DummyDiscovery(database_url=db_url)
    print("Running process_source() to insert a candidate row...")
    count = discovery.process_source(
        src_row,
        dataset_label="verify",
        operation_id=None,
    )
    print(f"process_source returned count={count}\n")

    dbm = DatabaseManager(database_url=db_url)
    df = read_candidate_links(dbm.engine)
    print(f"Total candidate_links rows: {len(df)}")

    matches = []
    for _, row in df.iterrows():
        meta = row.get("meta")
        if isinstance(meta, str):
            try:
                meta_obj = json.loads(meta)
            except Exception:
                meta_obj = None
        else:
            meta_obj = meta
        if meta_obj and meta_obj.get("fallback_include_older"):
            matches.append(
                {"id": row.get("id"), "url": row.get("url"), "meta": meta_obj}
            )

    print(f"Found {len(matches)} rows with fallback_include_older=True")
    pprint(matches)
    dbm.close()


if __name__ == "__main__":
    main()
