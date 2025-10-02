import json
import pathlib
import sys

import pandas as pd
import pytest

# Ensure project root on sys.path
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crawler.discovery import NewsDiscovery


def test_prioritize_last_successful_method(monkeypatch):
    discovery = NewsDiscovery(database_url="sqlite:///:memory:")

    # Prepare a source row with last_successful_method set to 'newspaper4k'
    src = pd.Series(
        {
            "id": "p-source",
            "name": "Priority Source",
            "url": "https://example.org",
            "metadata": json.dumps({"last_successful_method": "newspaper4k"}),
        }
    )

    call_order = []

    def rss_stub(*a, **k):
        call_order.append("rss")
        return []

    def newspaper_stub(*a, **k):
        call_order.append("newspaper4k")
        return []

    def storysniffer_stub(*a, **k):
        call_order.append("storysniffer")
        return []

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", rss_stub)
    monkeypatch.setattr(discovery, "discover_with_newspaper4k", newspaper_stub)
    monkeypatch.setattr(discovery, "discover_with_storysniffer", storysniffer_stub)

    discovery.process_source(src, dataset_label="test", operation_id=None)

    # The first attempted method should be the preferred one
    assert call_order[0] == "newspaper4k"
