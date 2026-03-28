"""Tests for discovery method fallback logic.

When effective methods fail to produce stored articles, the system should
try alternative methods to prevent single-point-of-failure scenarios.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from src.crawler import discovery as discovery_module
from src.utils.discovery_outcomes import DiscoveryOutcome
from src.utils.telemetry import DiscoveryMethod


def _make_discovery_stub() -> discovery_module.NewsDiscovery:
    """Create a NewsDiscovery instance without __init__."""
    return discovery_module.NewsDiscovery.__new__(discovery_module.NewsDiscovery)


def _bind_method(instance: Any, func: Any) -> Any:
    """Bind a function as a method to an instance."""
    import types

    return types.MethodType(func, instance)


class _TelemetryStub:
    """Minimal telemetry stub for testing."""

    def __init__(self, effective_methods: list[DiscoveryMethod]):
        self.effective_methods = effective_methods
        self.recorded_failures: list[dict[str, Any]] = []

    def get_effective_discovery_methods(self, source_id: str):
        return list(self.effective_methods)

    def has_historical_data(self, source_id: str) -> bool:
        return len(self.effective_methods) > 0

    def record_site_failure(self, **kwargs: Any) -> None:
        self.recorded_failures.append(kwargs)

    def update_discovery_method_effectiveness(self, **kwargs: Any) -> None:
        pass


class _FakeDBManager:
    """Minimal database manager for testing."""

    def __init__(self):
        self.session = object()
        self.engine = self._make_mock_engine()

    def _make_mock_engine(self):
        class MockResult:
            def fetchone(self):
                return None

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


def test_fallback_when_effective_methods_find_zero_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that newspaper4k is tried when effective methods find 0 articles."""
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 50
    instance.cutoff_date = datetime.utcnow() - timedelta(days=7)
    instance.storysniffer = None
    instance.delay = 0
    instance.days_back = 7

    # RSS is effective, newspaper4k is NOT
    telemetry = _TelemetryStub([DiscoveryMethod.RSS_FEED])
    instance.telemetry = telemetry

    # Mock discovery methods
    rss_calls = []
    newspaper_calls = []

    def fake_rss(*_args, **_kwargs):
        rss_calls.append(1)
        # RSS returns 0 articles
        return ([], {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0})

    def fake_newspaper(_self, *_args, **kwargs):
        newspaper_calls.append(1)
        # Newspaper4k finds articles
        return [
            {
                "url": "https://example.com/article1",
                "publish_date": datetime.utcnow().isoformat(),
                "discovery_method": "newspaper4k",
            },
            {
                "url": "https://example.com/article2",
                "publish_date": datetime.utcnow().isoformat(),
                "discovery_method": "newspaper4k",
            },
        ]

    instance.discover_with_rss_feeds = _bind_method(instance, fake_rss)
    instance.discover_with_newspaper4k = _bind_method(instance, fake_newspaper)
    instance.discover_with_storysniffer = _bind_method(instance, lambda *_a, **_k: [])

    # Mock storage and helpers
    stored_candidates = []

    def fake_upsert(_session, **payload):
        stored_candidates.append(payload)

    monkeypatch.setattr("src.models.database.upsert_candidate_link", fake_upsert)

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: set()
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._update_source_meta = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_no_effective_methods = _bind_method(
        instance, lambda *_a, **_k: None
    )
    instance._create_db_manager = _bind_method(instance, lambda _self: _FakeDBManager())
    instance._discover_and_store_sections = _bind_method(instance, lambda *_a, **_k: [])

    source_row = pd.Series(
        {
            "id": "source-1",
            "name": "Example News",
            "url": "https://example.com",
            "metadata": {},
            "city": "City",
            "county": "County",
            "type_classification": "local",
        }
    )

    result = instance.process_source(source_row)

    # Verify RSS was tried (effective method)
    assert len(rss_calls) == 1

    # Verify newspaper4k was tried as fallback (even though not in effective_methods)
    assert len(newspaper_calls) == 1

    # Verify articles were stored from fallback
    assert len(stored_candidates) == 2
    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert result.articles_new == 2


def test_fallback_when_articles_discovered_but_all_filtered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test fallback when RSS finds articles but all get filtered during storage."""
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 50
    instance.cutoff_date = datetime.utcnow() - timedelta(days=7)
    instance.storysniffer = None
    instance.delay = 0
    instance.days_back = 7

    # RSS is effective, newspaper4k is NOT
    telemetry = _TelemetryStub([DiscoveryMethod.RSS_FEED])
    instance.telemetry = telemetry

    rss_calls = []
    newspaper_calls = []

    def fake_rss(*_args, **_kwargs):
        rss_calls.append(1)
        # RSS returns articles with /podcast/ URLs (will be filtered)
        return (
            [
                {
                    "url": "https://example.com/podcast/episode1",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
                {
                    "url": "https://example.com/podcast/episode2",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
            ],
            {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0},
        )

    def fake_newspaper(_self, *_args, **kwargs):
        newspaper_calls.append(1)
        # Newspaper4k finds real news articles
        return [
            {
                "url": "https://example.com/news/article1",
                "publish_date": datetime.utcnow().isoformat(),
                "discovery_method": "newspaper4k",
            },
        ]

    instance.discover_with_rss_feeds = _bind_method(instance, fake_rss)
    instance.discover_with_newspaper4k = _bind_method(instance, fake_newspaper)
    instance.discover_with_storysniffer = _bind_method(instance, lambda *_a, **_k: [])

    stored_candidates = []

    def fake_upsert(_session, **payload):
        stored_candidates.append(payload)

    monkeypatch.setattr("src.models.database.upsert_candidate_link", fake_upsert)

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: set()
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._update_source_meta = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_no_effective_methods = _bind_method(
        instance, lambda *_a, **_k: None
    )
    instance._create_db_manager = _bind_method(instance, lambda _self: _FakeDBManager())
    instance._discover_and_store_sections = _bind_method(instance, lambda *_a, **_k: [])

    source_row = pd.Series(
        {
            "id": "source-1",
            "name": "Example News",
            "url": "https://example.com",
            "metadata": {},
            "city": "City",
            "county": "County",
            "type_classification": "local",
        }
    )

    result = instance.process_source(source_row)

    # Verify RSS was tried
    assert len(rss_calls) == 1

    # Verify newspaper4k was tried as fallback (because RSS articles were all filtered)
    assert len(newspaper_calls) == 1

    # Verify only newspaper4k articles were stored (podcast URLs filtered)
    assert len(stored_candidates) == 1
    assert "news/article1" in stored_candidates[0]["url"]
    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND


def test_no_fallback_when_effective_methods_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that BOTH RSS and newspaper4k always run (no fallback logic).

    Per requirement: we should always use RSS first and then homepage/section
    discovery regardless of whether RSS found articles.
    """
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 50
    instance.cutoff_date = datetime.utcnow() - timedelta(days=7)
    instance.storysniffer = None
    instance.delay = 0
    instance.days_back = 7

    # RSS is effective
    telemetry = _TelemetryStub([DiscoveryMethod.RSS_FEED])
    instance.telemetry = telemetry

    rss_calls = []
    newspaper_calls = []

    def fake_rss(*_args, **_kwargs):
        rss_calls.append(1)
        # RSS finds valid articles
        return (
            [
                {
                    "url": "https://example.com/article1",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
            ],
            {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0},
        )

    def fake_newspaper(_self, *_args, **kwargs):
        newspaper_calls.append(1)
        return []

    instance.discover_with_rss_feeds = _bind_method(instance, fake_rss)
    instance.discover_with_newspaper4k = _bind_method(instance, fake_newspaper)
    instance.discover_with_storysniffer = _bind_method(instance, lambda *_a, **_k: [])

    stored_candidates = []

    def fake_upsert(_session, **payload):
        stored_candidates.append(payload)

    monkeypatch.setattr("src.models.database.upsert_candidate_link", fake_upsert)

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: set()
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._update_source_meta = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_no_effective_methods = _bind_method(
        instance, lambda *_a, **_k: None
    )
    instance._create_db_manager = _bind_method(instance, lambda _self: _FakeDBManager())
    instance._discover_and_store_sections = _bind_method(instance, lambda *_a, **_k: [])

    source_row = pd.Series(
        {
            "id": "source-1",
            "name": "Example News",
            "url": "https://example.com",
            "metadata": {},
            "city": "City",
            "county": "County",
            "type_classification": "local",
        }
    )

    result = instance.process_source(source_row)

    # Verify RSS was tried
    assert len(rss_calls) == 1

    # Verify newspaper4k WAS tried (always runs for comprehensive discovery)
    assert len(newspaper_calls) == 1

    # Verify article was stored from RSS
    assert len(stored_candidates) == 1
    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND


def test_fallback_only_tries_newspaper4k_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that newspaper4k is not tried multiple times if already attempted."""

    # Mock safe_execute to prevent database errors
    def fake_safe_execute(_session, sql, params=None):
        return None

    monkeypatch.setattr("src.models.database.safe_execute", fake_safe_execute)

    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 50
    instance.cutoff_date = datetime.utcnow() - timedelta(days=7)
    instance.storysniffer = None
    instance.delay = 0
    instance.days_back = 7

    # Both RSS and newspaper4k are effective
    telemetry = _TelemetryStub([DiscoveryMethod.RSS_FEED, DiscoveryMethod.NEWSPAPER4K])
    instance.telemetry = telemetry

    rss_calls = []
    newspaper_calls = []

    def fake_rss(*_args, **_kwargs):
        rss_calls.append(1)
        # RSS returns podcast URLs (will be filtered)
        return (
            [
                {
                    "url": "https://example.com/podcast/episode1",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
            ],
            {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0},
        )

    def fake_newspaper(_self, *_args, **kwargs):
        newspaper_calls.append(1)
        # Newspaper4k also finds 0 articles
        return []

    instance.discover_with_rss_feeds = _bind_method(instance, fake_rss)
    instance.discover_with_newspaper4k = _bind_method(instance, fake_newspaper)
    instance.discover_with_storysniffer = _bind_method(instance, lambda *_a, **_k: [])

    stored_candidates = []

    def fake_upsert(_session, **payload):
        stored_candidates.append(payload)

    monkeypatch.setattr("src.models.database.upsert_candidate_link", fake_upsert)

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: set()
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._update_source_meta = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_no_effective_methods = _bind_method(
        instance, lambda *_a, **_k: None
    )
    instance._create_db_manager = _bind_method(instance, lambda _self: _FakeDBManager())
    instance._discover_and_store_sections = _bind_method(instance, lambda *_a, **_k: [])

    source_row = pd.Series(
        {
            "id": "source-1",
            "name": "Example News",
            "url": "https://example.com",
            "metadata": {},
            "city": "City",
            "county": "County",
            "type_classification": "local",
        }
    )

    result = instance.process_source(source_row)

    # Verify RSS was tried
    assert len(rss_calls) == 1

    # Verify newspaper4k was tried ONCE (as effective method, not again as fallback)
    assert len(newspaper_calls) == 1

    # No articles stored (podcast was filtered out-of-scope)
    assert len(stored_candidates) == 0
    # Outcome is UNKNOWN_ERROR because articles were found but all filtered
    assert result.outcome == DiscoveryOutcome.UNKNOWN_ERROR


def test_fallback_stats_merged_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that stats from fallback discovery are merged correctly."""

    # Mock safe_execute to prevent database errors
    def fake_safe_execute(_session, sql, params=None):
        return None

    monkeypatch.setattr("src.models.database.safe_execute", fake_safe_execute)

    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 50
    instance.cutoff_date = datetime.utcnow() - timedelta(days=7)
    instance.storysniffer = None
    instance.delay = 0
    instance.days_back = 7

    # RSS is effective
    telemetry = _TelemetryStub([DiscoveryMethod.RSS_FEED])
    instance.telemetry = telemetry

    def fake_rss(*_args, **_kwargs):
        # RSS finds podcasts and one duplicate
        return (
            [
                {
                    "url": "https://example.com/podcast/episode1",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
                {
                    "url": "https://example.com/existing",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
            ],
            {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0},
        )

    def fake_newspaper(_self, *_args, **kwargs):
        # Fallback finds 2 new articles
        return [
            {
                "url": "https://example.com/news/article1",
                "publish_date": datetime.utcnow().isoformat(),
                "discovery_method": "newspaper4k",
            },
            {
                "url": "https://example.com/news/article2",
                "publish_date": datetime.utcnow().isoformat(),
                "discovery_method": "newspaper4k",
            },
        ]

    instance.discover_with_rss_feeds = _bind_method(instance, fake_rss)
    instance.discover_with_newspaper4k = _bind_method(instance, fake_newspaper)
    instance.discover_with_storysniffer = _bind_method(instance, lambda *_a, **_k: [])

    stored_candidates = []

    def fake_upsert(_session, **payload):
        stored_candidates.append(payload)

    monkeypatch.setattr("src.models.database.upsert_candidate_link", fake_upsert)

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: {"https://example.com/existing"}
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._update_source_meta = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._reset_no_effective_methods = _bind_method(
        instance, lambda *_a, **_k: None
    )
    instance._create_db_manager = _bind_method(instance, lambda _self: _FakeDBManager())
    instance._discover_and_store_sections = _bind_method(instance, lambda *_a, **_k: [])

    source_row = pd.Series(
        {
            "id": "source-1",
            "name": "Example News",
            "url": "https://example.com",
            "metadata": {},
            "city": "City",
            "county": "County",
            "type_classification": "local",
        }
    )

    result = instance.process_source(source_row)

    # Verify correct stats
    # RSS: 2 found (1 podcast filtered, 1 duplicate)
    # Fallback: 2 found (2 new articles stored)
    assert result.articles_found == 4  # Total from both methods
    assert result.articles_new == 2  # Only from fallback
    assert result.articles_duplicate == 1  # From RSS
    assert result.metadata["stored_count"] == 2  # Only fallback articles stored
    assert result.metadata["out_of_scope_skipped"] == 1  # Podcast filtered
