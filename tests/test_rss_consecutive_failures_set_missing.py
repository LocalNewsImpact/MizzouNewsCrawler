import json
import pathlib
import sys

import pandas as pd

# Make the local `src` package importable for tests
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.crawler.discovery import RSS_MISSING_THRESHOLD, NewsDiscovery


def test_repeated_non_network_failures_set_rss_missing(monkeypatch):
    """After RSS_MISSING_THRESHOLD non-network failures, rss_missing is set."""
    nd = NewsDiscovery(timeout=1, delay=0)

    recorded_updates = []
    monkeypatch.setattr(nd, "_update_source_meta", lambda sid, updates: recorded_updates.append(updates))

    # Simulate RSS discovery with no network errors but no successful feeds
    def fake_rss(*args, **kwargs):
        return ([], {"feeds_tried": 1, "feeds_successful": 0, "network_errors": 0})

    monkeypatch.setattr(nd, "discover_with_rss_feeds", fake_rss)
    monkeypatch.setattr(nd, "discover_with_newspaper4k", lambda *a, **k: [])
    monkeypatch.setattr(nd, "discover_with_storysniffer", lambda *a, **k: [])

    source_row = pd.Series({
        "url": "https://example.com",
        "name": "Example",
        "id": "test-source-2",
        "metadata": None,
        "city": None,
        "county": None,
        "type_classification": None,
    })

    # Monkeypatch DatabaseManager used in discovery to return a metadata
    # row with rss_consecutive_failures = threshold - 1 so a single call
    # will push it over the threshold deterministically.
    class FakeResult:
        def __init__(self, val):
            self._val = val

        def fetchone(self):
            return (self._val,)

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            # Return a JSON string similar to what's stored in the DB
            return FakeResult(json.dumps({"rss_consecutive_failures": RSS_MISSING_THRESHOLD - 1}))

    class FakeEngine:
        def connect(self):
            return FakeConn()

    class FakeDBManager:
        def __init__(self, url):
            self.engine = FakeEngine()

        def close(self):
            pass

        # Support use as a context manager (used by discovery.process_source)
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            try:
                self.close()
            except Exception:
                pass
            return False

    monkeypatch.setattr("src.crawler.discovery.DatabaseManager", FakeDBManager)

    # Run the process once (our fake DB already starts one short of threshold)
    nd.process_source(source_row, dataset_label=None, operation_id=None)

    # Ensure we saw an update that sets rss_missing or increments the counter
    found_missing = any(
        "rss_missing" in u and u.get("rss_missing")
        for u in recorded_updates
    )

    found_count = any(
        (
            "rss_consecutive_failures" in u
            and u.get("rss_consecutive_failures", 0) >= RSS_MISSING_THRESHOLD
        )
        for u in recorded_updates
    )

    assert (
        found_missing or found_count
    ), "rss_missing was not set after repeated non-network failures"
