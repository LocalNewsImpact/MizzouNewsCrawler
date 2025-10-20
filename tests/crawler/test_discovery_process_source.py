import datetime
from typing import Any

import pandas as pd
import pytest

from src.crawler.discovery import (
    DiscoveryMethod,
    DiscoveryResult,
    NewsDiscovery,
)
from src.utils.discovery_outcomes import DiscoveryOutcome


class _TelemetryStub:
    def __init__(self, methods: list[DiscoveryMethod]):
        self._methods = methods
        self.recorded_failures: list[dict[str, Any]] = []
        self.updated_methods: list[dict[str, Any]] = []

    def get_effective_discovery_methods(self, source_id: str):
        return list(self._methods)

    def update_discovery_method_effectiveness(self, **payload):
        self.updated_methods.append(payload)

    def record_site_failure(self, *args, **kwargs):
        self.recorded_failures.append({"args": args, "kwargs": kwargs})


class _DummyDBManager:
    def __init__(self):
        self.session = object()
        # Mock engine for dataset resolution
        self.engine = self._make_mock_engine()

    def _make_mock_engine(self):
        """Create a mock engine that returns dataset-a UUID."""
        class MockResult:
            def fetchone(self):
                # Return a mock UUID for dataset-a lookup
                return ("dataset-uuid-a",)

        class MockConnection:
            def execute(self, query, params=None):
                return MockResult()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class MockEngine:
            def connect(self):
                return MockConnection()

            def begin(self):
                return MockConnection()

        return MockEngine()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture()
def discovery_setup(monkeypatch):
    stored_candidates: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        lambda _session, **payload: stored_candidates.append(payload),
    )

    telemetry_stub = _TelemetryStub([DiscoveryMethod.RSS_FEED])
    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda **_kwargs: telemetry_stub,
    )

    nd = NewsDiscovery(
        database_url="sqlite://",
    )

    nd.storysniffer = None
    monkeypatch.setattr(
        nd,
        "_create_db_manager",
        lambda: _DummyDBManager(),
    )

    # Avoid touching the real database helpers during the test
    monkeypatch.setattr(
        nd,
        "_get_existing_urls_for_source",
        lambda _source_id: {"https://example.com/existing"},
    )
    monkeypatch.setattr(
        nd,
        "_collect_allowed_hosts",
        lambda _row, _meta: {"example.com"},
    )
    monkeypatch.setattr(nd, "_update_source_meta", lambda *args, **kwargs: None)
    monkeypatch.setattr(nd, "_increment_rss_failure", lambda *args, **kwargs: None)
    monkeypatch.setattr(nd, "_reset_rss_failure_state", lambda *args, **kwargs: None)

    now_iso = datetime.datetime.utcnow().isoformat()
    old_iso = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat()

    articles = [
        {
            "url": "https://example.com/new-story",
            "publish_date": now_iso,
            "metadata": {"section": "local"},
            "discovery_method": "rss_feed",
        },
        {
            "url": "https://example.com/existing",
            "publish_date": now_iso,
        },
        {
            "url": "https://example.com/old-story",
            "publish_date": old_iso,
        },
        {
            "url": "https://othersite.com/out-of-scope",
            "publish_date": now_iso,
        },
        {
            "url": None,
        },
    ]

    def fake_rss(*_args, **_kwargs):
        return (
            articles,
            {
                "feeds_tried": 1,
                "feeds_successful": 1,
                "network_errors": 0,
            },
        )

    monkeypatch.setattr(nd, "discover_with_rss_feeds", fake_rss)
    monkeypatch.setattr(nd, "discover_with_newspaper4k", lambda *args, **kwargs: [])
    monkeypatch.setattr(nd, "discover_with_storysniffer", lambda *args, **kwargs: [])

    source_row = pd.Series(
        {
            "id": "source-1",
            "name": "Example News",
            "url": "https://example.com",
            "metadata": {},
            "city": "Example City",
            "county": "Example County",
            "type_classification": "local",
        }
    )

    return nd, source_row, stored_candidates


def test_process_source_classifies_and_stores_articles(discovery_setup):
    nd, source_row, stored = discovery_setup

    result: DiscoveryResult = nd.process_source(
        source_row,
        dataset_label="dataset-a",
    )

    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert result.articles_found == 5
    assert result.articles_new == 1
    assert result.articles_duplicate == 1
    assert result.articles_expired == 1
    assert result.metadata["stored_count"] == 1
    assert result.metadata["out_of_scope_skipped"] == 1
    assert result.method_used == "rss_feed"

    assert len(stored) == 1
    candidate = stored[0]
    assert candidate["url"] == "https://example.com/new-story"
    assert candidate["source_id"] == "source-1"
    # dataset_id is now a UUID resolved from dataset label
    assert candidate["dataset_id"] == "dataset-uuid-a"
    assert candidate["meta"]["publish_date"].startswith("20")
    assert candidate["meta"]["section"] == "local"
