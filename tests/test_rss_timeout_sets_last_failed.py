import pathlib
import sys

import pandas as pd

# Make local `src` importable for tests
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.crawler.discovery import NewsDiscovery


def test_timeout_records_rss_last_failed(monkeypatch):
    """Transient network errors record rss_last_failed but do not set rss_missing."""
    nd = NewsDiscovery(timeout=1, delay=0)

    recorded_updates = []
    monkeypatch.setattr(
        nd, "_update_source_meta", lambda sid, updates: recorded_updates.append(updates)
    )

    def fake_rss(*args, **kwargs):
        return ([], {"feeds_tried": 1, "feeds_successful": 0, "network_errors": 1})

    monkeypatch.setattr(nd, "discover_with_rss_feeds", fake_rss)
    monkeypatch.setattr(nd, "discover_with_newspaper4k", lambda *a, **k: [])
    monkeypatch.setattr(nd, "discover_with_storysniffer", lambda *a, **k: [])

    source_row = pd.Series(
        {
            "url": "https://example.com",
            "name": "Example",
            "id": "test-source-1",
            "metadata": None,
            "city": None,
            "county": None,
            "type_classification": None,
        }
    )

    nd.process_source(source_row, dataset_label=None, operation_id=None)

    assert recorded_updates, "_update_source_meta was not called"

    found_last_failed = any("rss_last_failed" in u for u in recorded_updates)
    found_rss_missing = any("rss_missing" in u and u.get("rss_missing") for u in recorded_updates)

    assert found_last_failed
    assert not found_rss_missing
    assert found_last_failed, "Expected rss_last_failed to be recorded for network errors"
