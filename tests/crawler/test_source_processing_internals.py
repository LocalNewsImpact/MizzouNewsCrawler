import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import Mock

import pandas as pd

from src.crawler.source_processing import SourceProcessor
from src.utils.telemetry import DiscoveryMethod


class _TelemetryStub:
    def __init__(self, methods: list[DiscoveryMethod]):
        self._methods = methods

    def get_effective_discovery_methods(self, source_id: str) -> list[DiscoveryMethod]:
        return list(self._methods)

    def has_historical_data(self, source_id: str) -> bool:
        # Return True if there are any methods (simulating that data exists)
        return len(self._methods) > 0


class _BaseDiscoveryStub:
    def __init__(self, telemetry: Any = None, retry_days: int = 90):
        self.telemetry = telemetry
        self.max_articles_per_source = 10
        self.storysniffer = None
        self._retry_days = retry_days

    def _get_existing_urls_for_source(self, source_id: str) -> set[str]:
        return set()

    def _collect_allowed_hosts(self, _row: pd.Series, _meta: Any) -> set[str]:
        return {"example.com"}

    def _rss_retry_window_days(self, _freq: Any) -> int:
        return self._retry_days


def _make_series(metadata: dict[str, Any] | None = None) -> pd.Series:
    return pd.Series(
        {
            "id": "source-1",
            "name": "Example Source",
            "url": "https://example.com",
            "metadata": json.dumps(metadata or {}),
        }
    )


def test_source_processor_prioritizes_last_successful_method():
    telemetry = _TelemetryStub([DiscoveryMethod.NEWSPAPER4K, DiscoveryMethod.RSS_FEED])

    class _DiscoveryStub(_BaseDiscoveryStub):
        def _get_existing_urls_for_source(self, source_id: str) -> set[str]:
            return set()

        def _collect_allowed_hosts(self, _row: pd.Series, _meta: Any) -> set[str]:
            return {"example.com"}

    discovery = _DiscoveryStub(telemetry=telemetry)

    source_row = _make_series({"last_successful_method": "storysniffer"})
    processor = SourceProcessor(discovery=discovery, source_row=source_row)
    processor._initialize_context()

    assert processor.effective_methods[0] == DiscoveryMethod.STORYSNIFFER
    assert DiscoveryMethod.STORYSNIFFER in processor.effective_methods


def test_source_processor_should_skip_rss_when_recent_missing(monkeypatch):
    now_iso = datetime.utcnow().isoformat()
    recent_meta = {
        "rss_missing": now_iso,
        "frequency": "weekly",
    }

    old_iso = (datetime.utcnow() - timedelta(days=120)).isoformat()
    old_meta = {
        "rss_missing": old_iso,
        "frequency": "weekly",
    }

    class _DiscoveryStub(_BaseDiscoveryStub):
        def __init__(self):
            super().__init__(telemetry=None, retry_days=30)

        def _get_existing_urls_for_source(self, source_id: str) -> set[str]:
            return set()

        def _collect_allowed_hosts(self, _row: pd.Series, _meta: Any) -> set[str]:
            return {"example.com"}

    recent_processor = SourceProcessor(
        discovery=_DiscoveryStub(),
        source_row=_make_series(recent_meta),
    )
    recent_processor._initialize_context()
    assert recent_processor._should_skip_rss()

    old_processor = SourceProcessor(
        discovery=_DiscoveryStub(),
        source_row=_make_series(old_meta),
    )
    old_processor._initialize_context()
    assert not old_processor._should_skip_rss()


def test_store_candidates_classification(monkeypatch):
    stored_payloads: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        lambda _session, **payload: stored_payloads.append(payload),
    )

    class _MockConnection:
        """Mock connection that can be used as context manager."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            # Return fake dataset result
            class _MockResult:
                def fetchone(self):
                    # Return a mock row with dataset id
                    # This simulates finding dataset-123
                    return ("dataset-123",)

            return _MockResult()

    class _RecordingManager:
        def __init__(self):
            self.session = object()
            # Mock engine attribute needed by dataset resolution
            self.engine = Mock()
            self.engine.connect = Mock(return_value=_MockConnection())

        def __enter__(self) -> "_RecordingManager":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    class _DiscoveryStub(_BaseDiscoveryStub):
        def __init__(self):
            super().__init__(telemetry=None)
            self._recent_cutoff = datetime.utcnow() - timedelta(days=3)

        def _get_existing_urls_for_source(self, source_id: str) -> set[str]:
            return {"https://example.com/duplicate"}

        def _collect_allowed_hosts(self, _row: pd.Series, _meta: Any) -> set[str]:
            return {"example.com"}

        def _normalize_host(self, host: str | None) -> str | None:
            if not host:
                return None
            return host.lower().split(":")[0]

        def _create_db_manager(self):
            return _RecordingManager()

        def _normalize_candidate_url(self, url: str) -> str:
            return (url or "").lower()

        def _is_recent_article(self, publish_date: datetime | None) -> bool:
            if publish_date is None:
                return True
            return publish_date >= self._recent_cutoff

        def _format_discovered_by(self, article_data: dict[str, Any]) -> str:
            method = article_data.get("discovery_method", "unknown")
            return f"formatted_{method}"

    discovery = _DiscoveryStub()
    source_row = _make_series()
    processor = SourceProcessor(
        discovery=discovery,
        source_row=source_row,
        dataset_label="dataset-123",
    )
    processor._initialize_context()

    now = datetime.utcnow()
    articles = [
        {
            "url": "https://example.com/new-story",
            "publish_date": now.isoformat(),
            "metadata": {"section": "local"},
            "discovery_method": "rss_feed",
        },
        {
            "url": "https://example.com/duplicate",
            "publish_date": now.isoformat(),
        },
        {
            "url": "https://example.com/expired",
            "publish_date": (now - timedelta(days=10)).isoformat(),
        },
        {
            "url": "https://othersite.com/out-of-scope",
            "publish_date": now.isoformat(),
        },
        {
            "url": None,
        },
    ]

    stats = processor._store_candidates(articles)

    assert stats["articles_found_total"] == len(articles)
    assert stats["articles_new"] == 1
    assert stats["articles_duplicate"] == 1
    assert stats["articles_expired"] == 1
    assert stats["articles_out_of_scope"] == 1
    assert stats["stored_count"] == 1

    assert len(stored_payloads) == 1
    stored = stored_payloads[0]
    assert stored["dataset_id"] == "dataset-123"
    assert stored["url"] == "https://example.com/new-story"
    assert stored["meta"]["section"] == "local"
    assert stored["discovered_by"].startswith("formatted_")


def test_accurate_logging_when_historical_data_exists_but_no_effective_methods(
    caplog,
):
    """Test that log messages accurately distinguish between:
    1. No historical data at all
    2. Historical data exists but no methods are effective
    """
    import logging

    caplog.set_level(logging.INFO)

    # Case 1: Historical data exists but no effective methods
    class _TelemetryWithHistory:
        def has_historical_data(self, source_id: str) -> bool:
            return True

        def get_effective_discovery_methods(
            self, source_id: str
        ) -> list[DiscoveryMethod]:
            # Historical data exists but doesn't meet effectiveness criteria
            return []

    class _DiscoveryWithHistory(_BaseDiscoveryStub):
        def __init__(self):
            super().__init__(telemetry=_TelemetryWithHistory())

    discovery = _DiscoveryWithHistory()
    source_row = _make_series()
    processor = SourceProcessor(discovery=discovery, source_row=source_row)
    processor._initialize_context()

    # Should NOT log "No historical data" but instead
    # "No effective methods found"
    assert processor.effective_methods == [
        DiscoveryMethod.RSS_FEED,
        DiscoveryMethod.NEWSPAPER4K,
        DiscoveryMethod.STORYSNIFFER,
    ]
    log_messages = [rec.message for rec in caplog.records]
    assert any("No effective methods found" in msg for msg in log_messages)
    assert not any(
        "No historical data" in msg and "No effective" not in msg
        for msg in log_messages
    )

    caplog.clear()

    # Case 2: No historical data at all
    class _TelemetryNoHistory:
        def has_historical_data(self, source_id: str) -> bool:
            return False

        def get_effective_discovery_methods(
            self, source_id: str
        ) -> list[DiscoveryMethod]:
            return []

    class _DiscoveryNoHistory(_BaseDiscoveryStub):
        def __init__(self):
            super().__init__(telemetry=_TelemetryNoHistory())

    discovery_no_hist = _DiscoveryNoHistory()
    processor_no_hist = SourceProcessor(
        discovery=discovery_no_hist, source_row=source_row
    )
    processor_no_hist._initialize_context()

    # Should log "No historical data"
    log_messages = [rec.message for rec in caplog.records]
    assert any("No historical data" in msg for msg in log_messages)
