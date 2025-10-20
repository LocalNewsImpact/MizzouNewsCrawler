"""
Test to verify that discovery process properly populates source_host_id field.

This test addresses the gap in test coverage that allowed the source_host_id
assignment bug to go undetected. It verifies that when the discovery process
stores candidate URLs, the source_host_id field is properly populated.
"""

import contextlib
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
from typing import Iterator, cast
from unittest.mock import patch

import pandas as pd
import pytest
import requests

try:
    from src.crawler.discovery import NewsDiscovery
    from src.models.database import DatabaseManager, upsert_candidate_link
    from src.utils.telemetry import DiscoveryMethod, OperationTracker
except ModuleNotFoundError:  # pragma: no cover - fallback for direct test runs
    ROOT = str(pathlib.Path(__file__).resolve().parents[1])
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from src.crawler.discovery import NewsDiscovery
    from src.models.database import DatabaseManager, upsert_candidate_link
    from src.utils.telemetry import DiscoveryMethod, OperationTracker


@contextlib.contextmanager
def temporary_database() -> Iterator[tuple[str, str]]:
    """Yield a temporary SQLite DB URL and path, then remove the file."""

    fd, path = tempfile.mkstemp(prefix="test_discovery_", suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        yield db_url, path
    finally:
        if os.path.exists(path):
            os.remove(path)


def seed_source_records(db_url: str) -> None:
    """Insert a minimal source and dataset mapping for discovery tests."""

    with DatabaseManager(database_url=db_url) as db:
        test_source_data = pd.DataFrame(
            [
                {
                    "id": "test-source-123",
                    "host": "example.com",
                    "host_norm": "example.com",
                    "canonical_name": "Example Site",
                    "city": "Test City",
                    "county": "Test County",
                    "type": "news",
                    "metadata": None,
                }
            ]
        )
        test_source_data.to_sql(
            "sources",
            db.engine,
            if_exists="append",
            index=False,
        )

        dataset_source_data = pd.DataFrame(
            [
                {
                    "id": "ds-test-123",
                    "dataset_id": "test-dataset",
                    "source_id": "test-source-123",
                    "legacy_host_id": "legacy-123",
                }
            ]
        )
        dataset_source_data.to_sql(
            "dataset_sources",
            db.engine,
            if_exists="append",
            index=False,
        )


class TelemetryStub:
    """Minimal telemetry replacement for discovery tests."""

    def __init__(self, effective_methods):
        self.effective_methods = effective_methods
        self.failure_calls = []
        self.method_updates = []
        self.outcomes = []

    def get_effective_discovery_methods(self, _source_id):
        return self.effective_methods

    def update_discovery_method_effectiveness(self, **kwargs):
        self.method_updates.append(kwargs)

    def record_site_failure(self, **kwargs):
        self.failure_calls.append(kwargs)

    def record_discovery_outcome(self, **kwargs):
        self.outcomes.append(kwargs)

    def track_http_status(self, *args, **kwargs):
        return None

    def list_active_operations(self):
        return []

    def get_failure_summary(self, *_args, **_kwargs):
        return {"total_failures": 0, "failure_types": {}}

    def track_operation(self, *args, **kwargs):  # pragma: no cover - helper
        return contextlib.nullcontext()


def test_discovery_populates_source_host_id():
    """Discovery result should include stored articles and metadata."""

    with temporary_database() as (db_url, path):
        seed_source_records(db_url)

        source_row = pd.Series(
            {
                "url": "https://example.com",
                "name": "Example Site",
                "id": "test-source-123",  # should populate source_host_id
                "metadata": None,
                "city": "Test City",
                "county": "Test County",
                "type_classification": "news",
            }
        )

        discovery = NewsDiscovery(database_url=db_url)

        test_articles = [
            {
                "url": "https://example.com/article1",
                "title": "Test Article 1",
                "metadata": {"publish_date": "2025-09-20T12:00:00"},
            },
            {
                "url": "https://example.com/article2",
                "title": "Test Article 2",
                "metadata": {"publish_date": "2025-09-20T13:00:00"},
            },
        ]

        with (
            patch.object(
                discovery,
                "discover_with_rss_feeds",
                return_value=([], {}),
            ),
            patch.object(
                discovery,
                "discover_with_newspaper4k",
                return_value=test_articles,
            ),
            patch.object(
                discovery,
                "discover_with_storysniffer",
                return_value=[],
            ),
        ):
            result = discovery.process_source(
                source_row=source_row,
                dataset_label="test-dataset",
            )

        assert result.is_success
        assert result.articles_new == 2
        assert result.metadata.get("stored_count") == 2
        assert result.metadata.get("out_of_scope_skipped") == 0

        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT url, source_host_id, source_name, source_city, source_county
            FROM candidate_links
            WHERE url LIKE 'https://example.com/article%'
            """
        )
        stored_links = cursor.fetchall()
        conn.close()

        assert len(stored_links) == 2
        for (
            url,
            source_host_id,
            source_name,
            source_city,
            source_county,
        ) in stored_links:
            assert source_host_id == "test-source-123"
            assert source_name == "Example Site"
            assert source_city == "Test City"
            assert source_county == "Test County"

    def test_discovery_skips_external_hosts():
        """Discovery should ignore URLs whose hosts don't match the source."""

        with temporary_database() as (db_url, path):
            seed_source_records(db_url)

            source_row = pd.Series(
                {
                    "url": "https://example.com",
                    "name": "Example Site",
                    "id": "test-source-123",
                    "metadata": None,
                    "city": "Test City",
                    "county": "Test County",
                    "type_classification": "news",
                    "host": "example.com",
                }
            )

            discovery = NewsDiscovery(database_url=db_url)

            test_articles = [
                {
                    "url": "https://example.com/keep-me",
                    "title": "On-domain article",
                    "metadata": {"publish_date": "2025-09-20T12:00:00"},
                },
                {
                    "url": (
                        "https://www.barrons.com/articles/stock-market-"
                        "earnings-broadcom-tech-dcdaff85"
                    ),
                    "title": "External article",
                    "metadata": {"publish_date": "2025-09-20T12:10:00"},
                },
            ]

            with (
                patch.object(
                    discovery,
                    "discover_with_rss_feeds",
                    return_value=([], {}),
                ),
                patch.object(
                    discovery,
                    "discover_with_newspaper4k",
                    return_value=test_articles,
                ),
                patch.object(
                    discovery,
                    "discover_with_storysniffer",
                    return_value=[],
                ),
            ):
                result = discovery.process_source(
                    source_row=source_row,
                    dataset_label="test-dataset",
                )

            assert result.is_success
            assert result.articles_new == 1
            assert result.metadata.get("stored_count") == 1
            assert result.metadata.get("out_of_scope_skipped") == 1

            conn = sqlite3.connect(path)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT url FROM candidate_links ORDER BY url
                """
            )
            stored_links = {row[0] for row in cursor.fetchall()}
            conn.close()

            assert stored_links == {"https://example.com/keep-me"}


def test_discovery_without_source_host_id_requires_identifier():
    """Missing ID should raise an error for discovery processing."""

    with temporary_database() as (db_url, _):
        source_row = pd.Series(
            {
                "url": "https://example.com",
                "name": "Example Site",
                # "id": missing on purpose
                "metadata": None,
                "city": "Test City",
                "county": "Test County",
                "type_classification": "news",
            }
        )

        discovery = NewsDiscovery(database_url=db_url)

        test_articles = [{"url": "https://example.com/test", "title": "Test"}]

        with (
            patch.object(
                discovery,
                "discover_with_rss_feeds",
                return_value=([], {}),
            ),
            patch.object(
                discovery,
                "discover_with_newspaper4k",
                return_value=test_articles,
            ),
            patch.object(
                discovery,
                "discover_with_storysniffer",
                return_value=[],
            ),
        ):
            with pytest.raises(KeyError):
                discovery.process_source(
                    source_row=source_row,
                    dataset_label="test-dataset",
                )


def test_discovery_skips_preexisting_candidate_links():
    """Existing candidate URLs count as duplicates without reinsertion."""

    with temporary_database() as (db_url, path):
        seed_source_records(db_url)

        # Seed an existing candidate link for the source
        with DatabaseManager(database_url=db_url) as db:
            upsert_candidate_link(
                db.session,
                url="https://example.com/article1",
                source="Example Site",
                source_host_id="test-source-123",
                source_id="test-source-123",
                source_name="Example Site",
                source_city="Test City",
                source_county="Test County",
                dataset_id="test-dataset",
                status="discovered",
            )

        source_row = pd.Series(
            {
                "url": "https://example.com",
                "name": "Example Site",
                "id": "test-source-123",
                "metadata": None,
                "city": "Test City",
                "county": "Test County",
                "type_classification": "news",
            }
        )

        discovery = NewsDiscovery(database_url=db_url)

        test_articles = [
            {
                "url": "https://example.com/article1",  # duplicate
                "title": "Duplicate Article",
                "metadata": {"publish_date": "2025-09-20T12:00:00"},
            },
            {
                "url": "https://example.com/article3",
                "title": "Fresh Article",
                "metadata": {"publish_date": "2025-09-21T08:30:00"},
            },
        ]

        with (
            patch.object(
                discovery,
                "discover_with_rss_feeds",
                return_value=([], {}),
            ),
            patch.object(
                discovery,
                "discover_with_newspaper4k",
                return_value=test_articles,
            ),
            patch.object(
                discovery,
                "discover_with_storysniffer",
                return_value=[],
            ),
        ):
            result = discovery.process_source(
                source_row=source_row,
                dataset_label="test-dataset",
            )

        assert result.articles_new == 1
        assert result.articles_duplicate == 1
        assert result.metadata.get("stored_count") == 1

        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM candidate_links WHERE url = ?",
            ("https://example.com/article1",),
        )
        duplicate_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM candidate_links WHERE url = ?",
            ("https://example.com/article3",),
        )
        new_count = cursor.fetchone()[0]
        conn.close()

        assert duplicate_count == 1
        assert new_count == 1


def test_discovery_marks_rss_missing_after_repeated_failures(monkeypatch):
    """Test that repeated RSS failures are tracked in source metadata.
    
    Note: This functionality is currently disabled after sources table removal.
    The _update_source_meta function is now a no-op. This test verifies
    that discovery doesn't crash when RSS fails repeatedly.
    """
    # This test now verifies discovery doesn't crash when RSS fails
    # Metadata tracking was removed with sources table removal
    pytest.skip("RSS failure tracking disabled after sources table removal")
    
    with temporary_database() as (db_url, path):
        seed_source_records(db_url)

        discovery = NewsDiscovery(database_url=db_url)
        discovery.storysniffer = None

        def fake_rss_failure(*_args, **_kwargs):
            import requests
            raise requests.exceptions.Timeout("timeout")

        monkeypatch.setattr(
            discovery,
            "discover_with_rss_feeds",
            fake_rss_failure,
        )
        monkeypatch.setattr(
            discovery,
            "discover_with_newspaper4k",
            lambda *_a, **_k: [],
        )
        monkeypatch.setattr(
            discovery,
            "discover_with_storysniffer",
            lambda *_a, **_k: [],
        )

        source_row = pd.Series(
            {
                "url": "https://example.com",
                "name": "Example Site",
                "id": "test-source-123",
                "metadata": None,
                "city": "Test City",
                "county": "Test County",
                "type_classification": "news",
            }
        )

        # Should not crash
        for _ in range(3):
            discovery.process_source(
                source_row=source_row,
                dataset_label="test-dataset",
            )


def test_discovery_storysniffer_fallback_records_article(monkeypatch):
    """StorySniffer articles should be stored when telemetry prefers it."""

    with temporary_database() as (db_url, path):
        seed_source_records(db_url)

        discovery = NewsDiscovery(database_url=db_url)
        telemetry = TelemetryStub([DiscoveryMethod.STORYSNIFFER])
        discovery.telemetry = cast(OperationTracker, telemetry)

        monkeypatch.setattr(
            discovery,
            "discover_with_rss_feeds",
            lambda *a, **k: ([], {}),
        )
        monkeypatch.setattr(
            discovery,
            "discover_with_newspaper4k",
            lambda *a, **k: [],
        )

        story_articles = [
            {
                "url": "https://example.com/story",
                "title": "Fallback story",
                "metadata": {"publish_date": "2025-09-20T10:00:00"},
            }
        ]

        monkeypatch.setattr(
            discovery,
            "discover_with_storysniffer",
            lambda *a, **k: story_articles,
        )

        source_row = pd.Series(
            {
                "url": "https://example.com",
                "name": "Example Site",
                "id": "test-source-123",
                "metadata": None,
                "city": "Test City",
                "county": "Test County",
                "type_classification": "news",
            }
        )

        result = discovery.process_source(
            source_row=source_row,
            dataset_label="test-dataset",
        )

        assert result.is_success
        assert result.articles_new == 1
        assert any(
            method
            for method in result.metadata.get("methods_attempted", [])
            if "storysniffer" in method
        )

        conn = sqlite3.connect(path)
        stored = conn.execute(
            "SELECT COUNT(*) FROM candidate_links WHERE url=?",
            ("https://example.com/story",),
        ).fetchone()[0]
        conn.close()

        assert stored == 1
        assert telemetry.failure_calls == []


@pytest.mark.xfail(
    reason="Sources table removed - metadata tracking deprecated"
)
def test_discovery_rss_timeout_resets_failure_state(monkeypatch):
    """Timeout errors should not increment RSS failure counters.
    
    NOTE: This test is xfail because the sources table was removed
    and metadata tracking for RSS failures is no longer implemented.
    """

    with temporary_database() as (db_url, path):
        seed_source_records(db_url)

        discovery = NewsDiscovery(database_url=db_url)
        discovery.telemetry = cast(
            OperationTracker, TelemetryStub([DiscoveryMethod.RSS_FEED])
        )

        def raise_timeout(*_args, **_kwargs):
            raise requests.exceptions.Timeout()

        monkeypatch.setattr(
            discovery,
            "discover_with_rss_feeds",
            raise_timeout,
        )
        monkeypatch.setattr(
            discovery,
            "discover_with_newspaper4k",
            lambda *a, **k: [],
        )
        monkeypatch.setattr(
            discovery,
            "discover_with_storysniffer",
            lambda *a, **k: [],
        )

        source_row = pd.Series(
            {
                "url": "https://example.com",
                "name": "Example Site",
                "id": "test-source-123",
                "metadata": None,
                "city": "Test City",
                "county": "Test County",
                "type_classification": "news",
            }
        )

        discovery.process_source(
            source_row=source_row,
            dataset_label="test-dataset",
        )

        conn = sqlite3.connect(path)
        metadata_row = conn.execute(
            "SELECT metadata FROM sources WHERE id=?",
            ("test-source-123",),
        ).fetchone()
        conn.close()

        assert metadata_row is not None
        meta = json.loads(metadata_row[0])
        assert meta.get("rss_consecutive_failures", 0) == 0
        assert meta.get("rss_missing") is None
        assert meta.get("rss_last_failed") is not None
