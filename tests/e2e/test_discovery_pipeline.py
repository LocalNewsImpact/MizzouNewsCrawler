"""End-to-end discovery pipeline smoke test."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from src.crawler.discovery import NewsDiscovery
from src.models import CandidateLink, Source
from src.models.database import DatabaseManager
from src.telemetry.store import TelemetryStore
from src.utils.discovery_outcomes import DiscoveryOutcome
from src.utils.telemetry import DiscoveryMethod, OperationTracker


@dataclass
class RecordedOutcome:
    operation_id: str
    source_id: str
    source_name: str
    source_url: str
    discovery_result: Any


class StubTelemetry:
    """Minimal telemetry stub capturing discovery lifecycle events."""

    def __init__(self) -> None:
        self.operations: list[dict[str, Any]] = []
        self.discovery_outcomes: list[RecordedOutcome] = []
        self.method_updates: list[dict[str, Any]] = []
        self.site_failures: list[dict[str, Any]] = []

    @contextmanager
    def track_operation(self, operation_type, **kwargs):
        operation_id = f"op-{len(self.operations) + 1}"
        self.operations.append(
            {
                "id": operation_id,
                "operation_type": operation_type,
                "metadata": kwargs,
            }
        )
        tracker = SimpleNamespace(operation_id=operation_id)
        tracker.update_progress = lambda **_kwargs: None
        yield tracker

    def get_effective_discovery_methods(self, source_id: str):
        return [DiscoveryMethod.RSS_FEED]

    def update_discovery_method_effectiveness(self, *args, **kwargs):
        self.method_updates.append({"args": args, "kwargs": kwargs})

    def record_site_failure(self, **kwargs):
        self.site_failures.append(kwargs)

    def record_discovery_outcome(
        self,
        operation_id: str,
        source_id: str,
        source_name: str,
        source_url: str,
        discovery_result,
    ) -> None:
        self.discovery_outcomes.append(
            RecordedOutcome(
                operation_id=operation_id,
                source_id=source_id,
                source_name=source_name,
                source_url=source_url,
                discovery_result=discovery_result,
            )
        )


@pytest.fixture
def database_url(tmp_path) -> str:
    db_path = tmp_path / "discovery.db"
    return f"sqlite:///{db_path}"


@pytest.fixture
def source_id(database_url: str) -> str:
    identifier = str(uuid.uuid4())
    with DatabaseManager(database_url) as db:
        db.session.add(
            Source(
                id=identifier,
                host="example.com",
                host_norm="example.com",
                canonical_name="Example News",
                city="Columbia",
                county="Boone",
                type="news",
                meta={"frequency": "daily"},
            )
        )
        db.session.commit()
    return identifier


def _make_recent_article(slug: str) -> dict[str, Any]:
    published = datetime.utcnow().replace(microsecond=0)
    return {
        "url": f"https://example.com/{slug}",
        "publish_date": published.isoformat(),
        "discovery_method": "rss_feed",
    }


def _ensure_discovery_attempted_column(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    sqlite_path = database_url.replace("sqlite:///", "", 1)
    with sqlite3.connect(sqlite_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
        if "discovery_attempted" not in columns:
            conn.execute("ALTER TABLE sources ADD COLUMN discovery_attempted TIMESTAMP")
            conn.commit()


def _add_source(
    db: DatabaseManager,
    *,
    host: str,
    name: str,
    frequency: str = "weekly",
    last_discovery_iso: str | None = None,
):
    meta = {"frequency": frequency}
    if last_discovery_iso:
        meta["last_discovery_at"] = last_discovery_iso

    source = Source(
        id=str(uuid.uuid4()),
        host=host,
        host_norm=host,
        canonical_name=name,
        city="Columbia",
        county="Boone",
        type="news",
        meta=meta,
    )
    db.session.add(source)
    return source


def _patch_noop_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def rss_stub(self, *_args, **_kwargs):
        summary = {
            "feeds_tried": 0,
            "feeds_successful": 0,
            "network_errors": 0,
        }
        return [], summary

    def _no_articles(*_args, **_kwargs):
        return []

    monkeypatch.setattr(NewsDiscovery, "discover_with_rss_feeds", rss_stub)
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_newspaper4k",
        _no_articles,
    )
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_storysniffer",
        _no_articles,
    )


def test_run_discovery_happy_path(database_url: str, source_id: str, monkeypatch):
    telemetry_stub = StubTelemetry()

    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda *args, **kwargs: telemetry_stub,
    )

    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_rss_feeds",
        lambda self, *args, **kwargs: (
            [
                _make_recent_article("article-1"),
                _make_recent_article("article-2"),
            ],
            {
                "feeds_tried": 1,
                "feeds_successful": 1,
                "network_errors": 0,
            },
        ),
    )
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_newspaper4k",
        lambda self, *args, **kwargs: [],
    )
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_storysniffer",
        lambda self, *args, **kwargs: [],
    )

    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=4,
        delay=0,
    )

    stats = discovery.run_discovery(source_limit=1)

    assert stats["sources_processed"] == 1
    assert stats["sources_succeeded"] == 1
    assert stats["sources_with_content"] == 1
    assert stats["total_candidates_discovered"] == 2

    with DatabaseManager(database_url) as db:
        links = list(db.session.query(CandidateLink).all())

    stored_urls = {link.url for link in links}
    assert stored_urls == {
        "https://example.com/article-1",
        "https://example.com/article-2",
    }

    statuses = {link.status for link in links}
    assert statuses == {"discovered"}

    assert len(telemetry_stub.discovery_outcomes) == 1
    outcome = telemetry_stub.discovery_outcomes[0].discovery_result
    assert outcome.articles_new == 2
    assert outcome.metadata["stored_count"] == 2


def test_run_discovery_records_mixed_outcome_in_telemetry(
    database_url: str,
    source_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    telemetry_store = TelemetryStore(database=database_url, async_writes=False)
    tracker = OperationTracker(
        store=telemetry_store,
        database_url=database_url,
    )

    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda *args, **kwargs: tracker,
    )

    existing_url = "https://example.com/already-present"
    with DatabaseManager(database_url) as db:
        db.session.add(
            CandidateLink(
                url=existing_url,
                source="Example News",
                status="discovered",
                dataset_id="daily",
                source_id=source_id,
                source_host_id=source_id,
            )
        )
        db.session.commit()

    _ensure_discovery_attempted_column(database_url)

    expired_publish_date = (
        datetime.utcnow().replace(microsecond=0) - timedelta(days=30)
    ).isoformat()

    def rss_stub(*_args, **_kwargs):
        duplicate_article = {
            "url": existing_url,
            "publish_date": datetime.utcnow().isoformat(),
            "discovery_method": "rss_feed",
        }
        expired_article = {
            "url": "https://example.com/out-of-window",
            "publish_date": expired_publish_date,
            "discovery_method": "rss_feed",
        }
        summary = {
            "feeds_tried": 1,
            "feeds_successful": 1,
            "network_errors": 0,
        }
        return [duplicate_article, expired_article], summary

    monkeypatch.setattr(NewsDiscovery, "discover_with_rss_feeds", rss_stub)

    def _no_articles(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_newspaper4k",
        _no_articles,
    )
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_storysniffer",
        _no_articles,
    )

    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=5,
        delay=0,
    )

    stats = discovery.run_discovery(source_limit=1)

    telemetry_store.flush()

    sqlite_path = database_url.replace("sqlite:///", "", 1)
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM discovery_outcomes").fetchall()

    assert stats["sources_processed"] == 1
    assert stats["sources_no_content"] == 1
    assert stats["sources_with_content"] == 0

    assert len(rows) == 1
    row = rows[0]

    assert row["outcome"] == DiscoveryOutcome.MIXED_RESULTS.value
    assert row["articles_duplicate"] == 1
    assert row["articles_expired"] == 1

    metadata = json.loads(row["metadata"])
    assert metadata["methods_attempted"][0] == "rss_feed"
    assert metadata["stored_count"] == 0


def test_run_discovery_duplicate_only_records_outcome(
    database_url: str,
    source_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    telemetry_store = TelemetryStore(database=database_url, async_writes=False)
    tracker = OperationTracker(
        store=telemetry_store,
        database_url=database_url,
    )

    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda *args, **kwargs: tracker,
    )

    duplicate_url = "https://example.com/dup-article"
    with DatabaseManager(database_url) as db:
        db.session.add(
            CandidateLink(
                url=duplicate_url,
                source="Example News",
                status="discovered",
                dataset_id="daily",
                source_id=source_id,
                source_host_id=source_id,
            )
        )
        db.session.commit()

    _ensure_discovery_attempted_column(database_url)

    def duplicate_rss(*_args, **_kwargs):
        article = {
            "url": duplicate_url,
            "publish_date": datetime.utcnow().isoformat(),
            "discovery_method": "rss_feed",
        }
        summary = {
            "feeds_tried": 1,
            "feeds_successful": 1,
            "network_errors": 0,
        }
        return [article], summary

    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_rss_feeds",
        duplicate_rss,
    )

    def _no_articles(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_newspaper4k",
        _no_articles,
    )
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_storysniffer",
        _no_articles,
    )

    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=5,
        delay=0,
    )

    stats = discovery.run_discovery(source_limit=1)

    telemetry_store.flush()

    sqlite_path = database_url.replace("sqlite:///", "", 1)
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM discovery_outcomes").fetchall()

    assert stats["sources_processed"] == 1
    assert stats["sources_succeeded"] == 1
    assert stats["sources_no_content"] == 1
    assert stats["total_candidates_discovered"] == 0

    with DatabaseManager(database_url) as db:
        stored_urls = {link.url for link in db.session.query(CandidateLink).all()}

    assert stored_urls == {duplicate_url}

    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == DiscoveryOutcome.DUPLICATES_ONLY.value
    assert row["articles_duplicate"] == 1
    assert row["articles_new"] == 0

    metadata = json.loads(row["metadata"])
    assert metadata["methods_attempted"][0] == "rss_feed"
    assert metadata["stored_count"] == 0


def test_run_discovery_rss_timeout_uses_fallback_and_records_failure(
    database_url: str,
    source_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    telemetry_stub = StubTelemetry()

    monkeypatch.setattr(
        telemetry_stub,
        "get_effective_discovery_methods",
        lambda *_args, **_kwargs: [
            DiscoveryMethod.RSS_FEED,
            DiscoveryMethod.NEWSPAPER4K,
        ],
    )

    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda *args, **kwargs: telemetry_stub,
    )

    _ensure_discovery_attempted_column(database_url)

    fallback_calls: list[Any] = []

    def rss_failure(*_args, **_kwargs):
        raise requests.exceptions.Timeout("rss timed out")

    fallback_url = "https://example.com/fallback-success"

    def fallback_stub(self, *_args, **_kwargs):
        fallback_calls.append((_args, _kwargs))
        return [
            {
                "url": fallback_url,
                "publish_date": datetime.utcnow().isoformat(),
                "discovery_method": "newspaper4k",
            }
        ]

    def _no_articles(*_args, **_kwargs):
        return []

    monkeypatch.setattr(NewsDiscovery, "discover_with_rss_feeds", rss_failure)
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_newspaper4k",
        fallback_stub,
    )
    monkeypatch.setattr(
        NewsDiscovery,
        "discover_with_storysniffer",
        _no_articles,
    )

    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=5,
        delay=0,
    )

    stats = discovery.run_discovery(source_limit=1)

    assert len(fallback_calls) == 1

    assert stats["sources_processed"] == 1
    assert stats["sources_succeeded"] == 1
    assert stats["sources_with_content"] == 1
    assert stats["total_candidates_discovered"] == 1

    assert len(telemetry_stub.site_failures) == 1
    failure = telemetry_stub.site_failures[0]
    assert failure["discovery_method"] == "rss"

    assert len(telemetry_stub.discovery_outcomes) == 1
    outcome = telemetry_stub.discovery_outcomes[0].discovery_result
    assert outcome.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert outcome.articles_new == 1

    with DatabaseManager(database_url) as db:
        stored_links = list(db.session.query(CandidateLink).all())
        source_row = db.session.get(Source, source_id)

    assert len(stored_links) == 1
    stored_urls = {link.url for link in stored_links}
    assert stored_urls == {fallback_url}

    assert source_row is not None
    source_meta = source_row.meta or {}
    assert "rss_last_failed" in source_meta
    assert source_meta.get("rss_missing") in (None, "")


def test_due_only_respects_metadata_and_updates_state(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
):
    telemetry_stub = StubTelemetry()

    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda *_args, **_kwargs: telemetry_stub,
    )
    _patch_noop_discovery(monkeypatch)

    now = datetime.utcnow().replace(microsecond=0)
    due_last = (now - timedelta(days=8)).isoformat()
    recent_last = (now - timedelta(days=2)).isoformat()

    with DatabaseManager(database_url) as db:
        due_source = _add_source(
            db,
            host="due.example.com",
            name="Due Source",
            frequency="weekly",
            last_discovery_iso=due_last,
        )
        recent_source = _add_source(
            db,
            host="recent.example.com",
            name="Recent Source",
            frequency="weekly",
            last_discovery_iso=recent_last,
        )
        db.session.commit()
        due_id = due_source.id
        recent_id = recent_source.id

    _ensure_discovery_attempted_column(database_url)

    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=3,
        delay=0,
    )

    stats = discovery.run_discovery(
        source_limit=5,
        due_only=True,
    )

    assert stats["sources_available"] == 2
    assert stats["sources_due"] == 1
    assert stats["sources_skipped"] == 1
    assert stats["sources_processed"] == 1
    assert stats["sources_no_content"] == 1

    assert len(telemetry_stub.discovery_outcomes) == 1

    with DatabaseManager(database_url) as db:
        refreshed_due = db.session.get(Source, due_id)
        refreshed_recent = db.session.get(Source, recent_id)

    assert refreshed_due is not None
    assert refreshed_recent is not None

    processed_last = refreshed_due.meta.get("last_discovery_at")
    assert processed_last is not None
    assert datetime.fromisoformat(processed_last) > datetime.fromisoformat(due_last)
    assert refreshed_recent.meta.get("last_discovery_at") == recent_last


def test_due_only_honors_host_limit(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
):
    telemetry_stub = StubTelemetry()

    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda *_args, **_kwargs: telemetry_stub,
    )
    _patch_noop_discovery(monkeypatch)

    baseline_last = (
        datetime.utcnow().replace(microsecond=0) - timedelta(days=10)
    ).isoformat()

    with DatabaseManager(database_url) as db:
        sources = []
        for idx in range(3):
            source = _add_source(
                db,
                host=f"host-{idx}.example.com",
                name=f"Source {idx}",
                frequency="weekly",
                last_discovery_iso=baseline_last,
            )
            sources.append(source.id)
        db.session.commit()

    _ensure_discovery_attempted_column(database_url)

    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=3,
        delay=0,
    )

    stats = discovery.run_discovery(
        source_limit=5,
        due_only=True,
        host_limit=1,
    )

    assert stats["sources_available"] == 3
    assert stats["sources_due"] == 1
    assert stats["sources_limited_by_host"] == 2
    assert stats["sources_processed"] == 1
    assert stats["sources_no_content"] == 1

    assert len(telemetry_stub.discovery_outcomes) == 1
    processed_id = telemetry_stub.discovery_outcomes[0].source_id

    with DatabaseManager(database_url) as db:
        processed = db.session.get(Source, processed_id)
        others = [
            db.session.get(Source, source_id)
            for source_id in sources
            if source_id != processed_id
        ]

    assert processed is not None
    processed_last = processed.meta.get("last_discovery_at")
    assert isinstance(processed_last, str)
    assert datetime.fromisoformat(processed_last) > datetime.fromisoformat(
        baseline_last
    )
    for other in others:
        assert other is not None
        assert other.meta.get("last_discovery_at") == baseline_last


def test_due_only_respects_existing_article_limit(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
):
    telemetry_stub = StubTelemetry()

    monkeypatch.setattr(
        "src.crawler.discovery.create_telemetry_system",
        lambda *_args, **_kwargs: telemetry_stub,
    )
    _patch_noop_discovery(monkeypatch)

    baseline_last = (
        datetime.utcnow().replace(microsecond=0) - timedelta(days=9)
    ).isoformat()

    with DatabaseManager(database_url) as db:
        first = _add_source(
            db,
            host="eligible.example.com",
            name="Eligible Source",
            frequency="weekly",
            last_discovery_iso=baseline_last,
        )
        second = _add_source(
            db,
            host="crowded.example.com",
            name="Crowded Source",
            frequency="weekly",
            last_discovery_iso=baseline_last,
        )
        db.session.commit()
        first_id = first.id
        second_id = second.id

    counts = iter([0, 2])

    def fake_existing_count(self, source_id: str) -> int:
        try:
            return next(counts)
        except StopIteration:
            return 0

    monkeypatch.setattr(
        NewsDiscovery,
        "_get_existing_article_count",
        fake_existing_count,
    )

    _ensure_discovery_attempted_column(database_url)

    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=3,
        delay=0,
    )

    stats = discovery.run_discovery(
        source_limit=5,
        due_only=True,
        existing_article_limit=1,
    )

    assert stats["sources_available"] == 2
    assert stats["sources_due"] == 2
    assert stats["sources_processed"] == 1
    assert stats["sources_no_content"] == 1
    assert stats["sources_skipped_existing"] == 1

    assert len(telemetry_stub.discovery_outcomes) == 1
    processed_id = telemetry_stub.discovery_outcomes[0].source_id

    with DatabaseManager(database_url) as db:
        processed = db.session.get(Source, processed_id)
        skipped = db.session.get(
            Source,
            second_id if processed_id == first_id else first_id,
        )

    assert processed is not None
    processed_last = processed.meta.get("last_discovery_at")
    assert isinstance(processed_last, str)
    assert datetime.fromisoformat(processed_last) > datetime.fromisoformat(
        baseline_last
    )

    assert skipped is not None
    assert skipped.meta.get("last_discovery_at") == baseline_last
