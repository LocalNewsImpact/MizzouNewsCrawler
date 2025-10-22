from __future__ import annotations

import json
import pickle
import types
from datetime import datetime, timedelta
from typing import Any, Iterable

import pandas as pd
import pytest
import requests

from src.crawler import discovery as discovery_module
from src.utils.discovery_outcomes import DiscoveryOutcome, DiscoveryResult
from src.utils.telemetry import DiscoveryMethod, DiscoveryMethodStatus


def _make_discovery_stub() -> discovery_module.NewsDiscovery:
    return discovery_module.NewsDiscovery.__new__(discovery_module.NewsDiscovery)


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _FakeConn:
    def __init__(
        self,
        select_row: Any,
        executed: list[tuple[Any, dict[str, Any]]] | None = None,
    ) -> None:
        self._select_row = select_row
        self._executed = executed

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def execute(self, statement: Any, params: dict[str, Any]) -> _FakeResult:
        text_repr = str(statement).upper()
        if "SELECT" in text_repr and "METADATA" in text_repr:
            return _FakeResult(self._select_row)
        if self._executed is not None:
            self._executed.append((statement, params))
        return _FakeResult(None)


class _FakeEngine:
    def __init__(
        self,
        begin_row: Any = None,
        connect_row: Any = None,
        executed: list[tuple[Any, dict[str, Any]]] | None = None,
    ) -> None:
        self._begin_row = begin_row
        self._connect_row = connect_row
        self._executed = executed

    def begin(self) -> _FakeConn:
        return _FakeConn(self._begin_row, self._executed)

    def connect(self) -> _FakeConn:
        row = self._connect_row if self._connect_row is not None else None
        return _FakeConn(row, self._executed)


class _FakeQuery:
    def __init__(self, records: dict[str, Any]):
        self._records = records
        self._filters: dict[str, Any] = {}

    def filter_by(self, **kwargs: Any) -> _FakeQuery:
        self._filters.update(kwargs)
        return self

    def first(self) -> Any:
        url = self._filters.get("url")
        if url is None:
            return None
        return self._records.get(url)


class _FakeSession:
    """Lightweight stand-in for a SQLAlchemy session."""

    def __init__(self) -> None:
        self._records: dict[str, Any] = {}
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, *_args: Any, **_kwargs: Any) -> _FakeQuery:
        return _FakeQuery(self._records)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        url = getattr(obj, "url", None)
        if isinstance(url, str):
            self._records[url] = obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ("Example.com", "example.com"),
        ("https://www.example.com/path", "example.com"),
        ("subdomain.example.com:8080", "subdomain.example.com"),
        (" user:pass@www.example.com ", "example.com"),
    ],
)
def test_normalize_host(value: str | None, expected: str | None) -> None:
    assert discovery_module.NewsDiscovery._normalize_host(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("one,two , three", ["one", "two", "three"]),
        (["alpha", "beta"], ["alpha", "beta"]),
        (("foo", "bar"), ["foo", "bar"]),
        ({"gamma", "delta"}, ["gamma", "delta"]),
    ],
)
def test_iter_host_candidates(
    value: Iterable[str] | str,
    expected: list[str],
) -> None:
    instance = _make_discovery_stub()
    result = instance._iter_host_candidates(value)  # type: ignore[arg-type]
    assert sorted(result) == sorted(expected)


def test_collect_allowed_hosts_aggregates_and_normalizes() -> None:
    instance = _make_discovery_stub()

    source_row = pd.Series(
        {
            "host": "Example.com",
            "host_norm": "example.net",
            "url": "https://news.example.org/feed",
        }
    )

    metadata: dict[str, Any] = {
        "alternate_hosts": ["www.example.com", "blog.example.com"],
        "allowed_domains": "alt.example.org, api.example.org",
        "host_aliases": ["news.example.org"],
        "ignored": "should not be used",
    }

    hosts = instance._collect_allowed_hosts(source_row, metadata)

    assert hosts == {
        "example.com",
        "example.net",
        "news.example.org",
        "alt.example.org",
        "api.example.org",
        "blog.example.com",
    }


@pytest.mark.parametrize(
    "metadata, expected",
    [
        (None, (False, None, None)),
        ({}, (False, None, None)),
        (
            {"rss_missing": "2024-01-01T00:00:00Z"},
            (True, "rss_missing", None),
        ),
        (
            {"rss_missing": True, "rss_consecutive_failures": 3},
            (True, "rss_missing", 3),
        ),
        (
            {"rss_consecutive_failures": "5"},
            (False, None, 5),
        ),
    ],
)
def test_should_skip_rss_from_meta(metadata, expected) -> None:
    result = discovery_module.NewsDiscovery._should_skip_rss_from_meta(metadata)
    assert result == expected


def test_extract_homepage_feed_urls_dedupes_and_resolves() -> None:
    html = """
    <html>
      <head>
        <link rel="alternate" type="application/rss+xml" href="/rss.xml" />
        <link rel="alternate" type="application/atom+xml"
              href="https://example.org/feed.atom" />
        <link rel="alternate" type="text/xml" href="/rss.xml" />
      </head>
    </html>
    """

    feeds = discovery_module.NewsDiscovery._extract_homepage_feed_urls(
        html,
        "https://example.org/section/",
    )

    assert feeds == [
        "https://example.org/rss.xml",
        "https://example.org/feed.atom",
    ]


def test_extract_homepage_feed_urls_returns_empty_for_missing_links() -> None:
    html = """<html><head><title>No feeds here</title></head></html>"""

    feeds = discovery_module.NewsDiscovery._extract_homepage_feed_urls(
        html,
        "https://example.org/",
    )

    assert feeds == []


def test_extract_homepage_article_candidates_filters_and_limits() -> None:
    html = """
    <html>
      <body>
        <a href="/news/2024/story-one">Story 1</a>
        <a href="https://example.org/ARTICLE/two">Story 2</a>
        <a href="mailto:tips@example.org">Email</a>
        <a href="https://other.com/news/elsewhere">External</a>
        <a href="/rss">RSS</a>
        <a href="/story-two">Story 3</a>
        <a href="/story-two">Story 3 Duplicate</a>
      </body>
    </html>
    """

    candidates = discovery_module.NewsDiscovery._extract_homepage_article_candidates(
        html,
        "https://example.org",
        rss_missing=False,
    )

    assert candidates == [
        "https://example.org/news/2024/story-one",
        "https://example.org/ARTICLE/two",
        "https://example.org/story-two",
    ]


def test_homepage_candidates_skip_feeds_when_missing() -> None:
    html = """
    <html>
      <body>
        <a href="/news/2024/story-one">Story 1</a>
        <a href="/rss">RSS</a>
      </body>
    </html>
    """

    candidates = discovery_module.NewsDiscovery._extract_homepage_article_candidates(
        html,
        "https://example.org",
        rss_missing=True,
        max_candidates=10,
    )

    assert candidates == [
        "https://example.org/news/2024/story-one",
    ]


def test_extract_homepage_article_candidates_honors_limit() -> None:
    html = """
    <html>
      <body>
        <a href="/news/1">1</a>
        <a href="/news/2">2</a>
        <a href="/news/3">3</a>
      </body>
    </html>
    """

    candidates = discovery_module.NewsDiscovery._extract_homepage_article_candidates(
        html,
        "https://example.org",
        max_candidates=2,
    )

    assert candidates == [
        "https://example.org/news/1",
        "https://example.org/news/2",
    ]


@pytest.mark.parametrize(
    "days_returned, expected",
    [
        (1, 2),
        (4, 7),
        (0, 2),
    ],
)
def test_rss_retry_window_days(
    monkeypatch: pytest.MonkeyPatch,
    days_returned: int,
    expected: int,
) -> None:
    def fake_parse(freq: str | None) -> int:
        if freq == "raise":
            raise ValueError("boom")
        return days_returned

    monkeypatch.setattr(
        discovery_module,
        "parse_frequency_to_days",
        fake_parse,
    )

    if days_returned == 0:
        freq = "zero"
    elif days_returned == 1:
        freq = "daily"
    else:
        freq = "weekly"

    assert discovery_module.NewsDiscovery._rss_retry_window_days(freq) == expected
    assert discovery_module.NewsDiscovery._rss_retry_window_days("raise") == 7


def test_is_recent_article_respects_cutoff() -> None:
    instance = _make_discovery_stub()
    instance.cutoff_date = datetime(2024, 1, 1)

    assert instance._is_recent_article(None) is True
    assert instance._is_recent_article(datetime(2024, 1, 2)) is True
    assert instance._is_recent_article(datetime(2023, 12, 31)) is False


def test_newspaper_build_worker_writes_urls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    recorded: dict[str, Any] = {}

    class FakeConfig:
        def __init__(self) -> None:
            self.fetch_images = False

    class FakeArticle:
        def __init__(self, url: str) -> None:
            self.url = url

    class FakePaper:
        def __init__(self, urls: list[str]) -> None:
            self.articles = [FakeArticle(url) for url in urls]

    def fake_build(target_url: str, config) -> FakePaper:
        recorded["target"] = target_url
        recorded["fetch_images"] = getattr(config, "fetch_images", None)
        return FakePaper(
            [
                "https://example.com/a",
                "https://example.com/b",
            ]
        )

    monkeypatch.setattr(discovery_module, "Config", FakeConfig)
    monkeypatch.setattr(discovery_module, "build", fake_build)

    out_file = tmp_path / "urls.pkl"

    discovery_module._newspaper_build_worker(
        "https://example.com",
        str(out_file),
        True,
    )

    with out_file.open("rb") as fh:
        urls = pickle.load(fh)

    assert urls == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert recorded == {
        "target": "https://example.com",
        "fetch_images": True,
    }


def test_update_source_meta_merges_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that _update_source_meta is a no-op after sources table removal.

    The sources table was removed and metadata updates are now skipped.
    This test verifies the function doesn't crash.
    """
    executed: list[tuple[Any, dict[str, Any]]] = []

    class FakeDBM:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.engine = _FakeEngine(
                begin_row=(json.dumps({"existing": 1}),),
                executed=executed,
            )

    monkeypatch.setattr(discovery_module, "DatabaseManager", FakeDBM)

    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"

    # Should not raise an exception (best-effort, skips update)
    instance._update_source_meta("source-1", {"new": 2})

    # Function should complete without error (metadata update is now skipped)
    # No assertion on executed since the UPDATE is commented out


def test_increment_rss_failure_increments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDBM:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.engine = _FakeEngine(
                connect_row=(json.dumps({"rss_consecutive_failures": 1}),),
            )

    updates: list[tuple[str, dict[str, Any]]] = []

    def fake_update(self, source_id: str, payload: dict[str, Any]) -> None:
        updates.append((source_id, payload))

    monkeypatch.setattr(discovery_module, "DatabaseManager", FakeDBM)
    monkeypatch.setattr(
        discovery_module.NewsDiscovery,
        "_update_source_meta",
        fake_update,
        raising=False,
    )

    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"

    instance._increment_rss_failure("source-2")

    assert updates == [("source-2", {"rss_consecutive_failures": 2})]


def test_increment_rss_failure_marks_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDBM:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.engine = _FakeEngine(
                connect_row=(json.dumps({"rss_consecutive_failures": 2}),),
            )

    updates: list[tuple[str, dict[str, Any]]] = []

    def fake_update(self, source_id: str, payload: dict[str, Any]) -> None:
        updates.append((source_id, payload))

    monkeypatch.setattr(discovery_module, "DatabaseManager", FakeDBM)
    monkeypatch.setattr(
        discovery_module.NewsDiscovery,
        "_update_source_meta",
        fake_update,
        raising=False,
    )

    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"

    instance._increment_rss_failure("source-3")

    assert len(updates) == 1
    source_id, payload = updates[0]
    assert source_id == "source-3"
    assert payload["rss_consecutive_failures"] == 3
    assert payload["rss_missing"]  # ISO timestamp string


class _FakeTracker:
    def __init__(self, telemetry: _FakeTelemetry) -> None:
        self.operation_id = "op-1"
        self._telemetry = telemetry

    def update_progress(
        self,
        *,
        processed: int,
        total: int,
        message: str,
    ) -> None:
        self._telemetry.tracker_updates.append(
            {
                "processed": processed,
                "total": total,
                "message": message,
            }
        )


class _TelemetryContext:
    def __init__(self, telemetry: _FakeTelemetry) -> None:
        self._telemetry = telemetry
        self._tracker = _FakeTracker(telemetry)

    def __enter__(self) -> _FakeTracker:
        return self._tracker

    def __exit__(self, *_exc: Any) -> bool:
        return False


class _FakeTelemetry:
    def __init__(self) -> None:
        self.outcomes: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.tracker_updates: list[dict[str, Any]] = []
        self.track_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.method_updates: list[dict[str, Any]] = []

    def track_operation(self, *args: Any, **kwargs: Any) -> _TelemetryContext:
        self.track_calls.append((args, kwargs))
        return _TelemetryContext(self)

    def record_discovery_outcome(
        self,
        *,
        operation_id: str,
        source_id: str,
        source_name: str,
        source_url: str,
        discovery_result: DiscoveryResult,
    ) -> None:
        self.outcomes.append(
            {
                "operation_id": operation_id,
                "source_id": source_id,
                "source_name": source_name,
                "source_url": source_url,
                "discovery_result": discovery_result,
            }
        )

    def record_site_failure(
        self,
        *,
        operation_id: str,
        site_url: str,
        error: Exception,
        site_name: str,
        discovery_method: str,
    ) -> None:
        self.failures.append(
            {
                "operation_id": operation_id,
                "site_url": site_url,
                "error": error,
                "site_name": site_name,
                "discovery_method": discovery_method,
            }
        )

    def update_discovery_method_effectiveness(self, **kwargs: Any) -> None:
        self.method_updates.append(kwargs)


def test_discover_with_storysniffer_records_success() -> None:
    telemetry = _FakeTelemetry()
    instance = _make_discovery_stub()

    instance.telemetry = telemetry  # type: ignore[attr-defined]
    storysniffer_stub = types.SimpleNamespace(
        guess=lambda _url: [
            {
                "url": "https://example.com/story-sniffed",
                "title": "StorySniffer Headline",
                "publish_date": datetime.utcnow().isoformat(),
            }
        ]
    )
    instance.storysniffer = storysniffer_stub  # type: ignore[attr-defined]

    articles = discovery_module.NewsDiscovery.discover_with_storysniffer(
        instance,
        "https://example.com",
        source_id="source-123",
        operation_id="op-1",
    )

    assert [a["url"] for a in articles] == ["https://example.com/story-sniffed"]
    assert telemetry.method_updates, "Telemetry update not captured"

    update = telemetry.method_updates[-1]
    assert update["discovery_method"] == DiscoveryMethod.STORYSNIFFER
    assert update["status"] == DiscoveryMethodStatus.SUCCESS
    assert update["articles_found"] == 1


def test_discover_with_storysniffer_records_server_error() -> None:
    telemetry = _FakeTelemetry()
    instance = _make_discovery_stub()

    instance.telemetry = telemetry  # type: ignore[attr-defined]

    class BoomSniffer:
        def guess(self, _url: str) -> list[str]:
            raise RuntimeError("story sniffer blew up")

    instance.storysniffer = BoomSniffer()  # type: ignore[attr-defined]

    articles = discovery_module.NewsDiscovery.discover_with_storysniffer(
        instance,
        "https://example.com",
        source_id="source-456",
        operation_id="op-2",
    )

    assert articles == []
    assert telemetry.method_updates, "Telemetry update not captured"

    update = telemetry.method_updates[-1]
    assert update["discovery_method"] == DiscoveryMethod.STORYSNIFFER
    assert update["status"] == DiscoveryMethodStatus.SERVER_ERROR
    assert update["articles_found"] == 0
    assert "story sniffer blew up" in (update.get("notes") or "")


def test_discover_with_newspaper4k_records_no_feed(monkeypatch):
    telemetry = _FakeTelemetry()
    instance = _make_discovery_stub()

    instance.telemetry = telemetry  # type: ignore[attr-defined]
    instance.session = types.SimpleNamespace(  # type: ignore[attr-defined]
        get=lambda *_args, **_kwargs: types.SimpleNamespace(
            status_code=200,
            text="<html><head></head><body>No feeds here</body></html>",
        )
    )
    instance.user_agent = "pytest-agent"  # type: ignore[attr-defined]
    instance.timeout = 1  # type: ignore[attr-defined]
    instance.max_articles_per_source = 5  # type: ignore[attr-defined]
    instance._get_existing_urls = lambda: set()  # type: ignore[attr-defined]

    articles = discovery_module.NewsDiscovery.discover_with_newspaper4k(
        instance,
        "https://example.com",
        source_id="source-789",
        operation_id="op-3",
        allow_build=False,
    )

    assert articles == []
    assert telemetry.method_updates, "Telemetry update not captured"

    update = telemetry.method_updates[-1]
    assert update["discovery_method"] == DiscoveryMethod.NEWSPAPER4K
    assert update["status"] == DiscoveryMethodStatus.NO_FEED
    assert update["articles_found"] == 0


def test_discover_with_rss_feeds_handles_transient_errors(monkeypatch):
    instance = _make_discovery_stub()
    instance.timeout = 3
    instance.max_articles_per_source = 10
    instance.cutoff_date = datetime.utcnow() - timedelta(days=3)
    instance._get_existing_urls = lambda: set()  # type: ignore[attr-defined]
    instance.telemetry = None  # type: ignore[attr-defined]

    def raise_exc(exc: Exception):
        def _raiser(_url: str, _timeout: int):
            raise exc

        return _raiser

    bad_response = _FakeResponse(200, b"bad-feed")
    good_response = _FakeResponse(200, b"good-feed")

    actions: list[Any] = [
        raise_exc(requests.exceptions.Timeout()),
        raise_exc(requests.exceptions.ConnectionError()),
        raise_exc(RuntimeError("boom")),
        _FakeResponse(404),
        _FakeResponse(429),
        _FakeResponse(500),
        _FakeResponse(418),
        bad_response,
        good_response,
    ]

    session = _SequenceSession(actions)
    instance.session = session  # type: ignore[attr-defined]

    published = datetime.utcnow().timetuple()

    def fake_parse(content: bytes):
        if content == bad_response.content:
            raise ValueError("malformed")

        return types.SimpleNamespace(
            entries=[
                {
                    "link": "https://example.com/final",
                    "published_parsed": published,
                    "title": "Final Article",
                    "summary": "Summary",
                    "author": "Author",
                }
            ],
            feed={"updated_parsed": published},
        )

    monkeypatch.setattr(discovery_module.feedparser, "parse", fake_parse)

    articles, summary = discovery_module.NewsDiscovery.discover_with_rss_feeds(
        instance,
        "https://example.com",
        custom_rss_feeds=["https://example.com/custom.xml"],
    )

    assert [a["url"] for a in articles] == ["https://example.com/final"]
    assert summary["feeds_tried"] == len(session.calls)
    assert summary["feeds_successful"] == 1
    assert summary["network_errors"] == 6


def test_discover_with_rss_feeds_returns_empty_on_not_found(monkeypatch):
    instance = _make_discovery_stub()
    instance.timeout = 2
    instance.max_articles_per_source = 5
    instance.cutoff_date = datetime.utcnow() - timedelta(days=1)
    instance._get_existing_urls = lambda: set()  # type: ignore[attr-defined]
    instance.telemetry = None  # type: ignore[attr-defined]

    class Always404Session:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url: str, timeout: int):
            self.calls += 1
            return _FakeResponse(404)

    session = Always404Session()
    instance.session = session  # type: ignore[attr-defined]

    articles, summary = discovery_module.NewsDiscovery.discover_with_rss_feeds(
        instance,
        "https://example.org",
        custom_rss_feeds=["https://example.org/feed.xml"],
    )

    assert articles == []
    assert summary == {
        "feeds_tried": session.calls,
        "feeds_successful": 0,
        "network_errors": 0,
    }


def list_active_operations(self) -> list[dict[str, Any]]:
    return []


def get_failure_summary(self, operation_id: str) -> dict[str, Any]:
    return {"total_failures": 0, "failure_types": {}}


def _bind_method(instance: Any, func):
    return types.MethodType(func, instance)


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class _SequenceSession:
    def __init__(self, sequence: list[Any]) -> None:
        self.sequence = sequence
        self.calls: list[str] = []

    def get(self, url: str, timeout: int):
        index = len(self.calls)
        if index >= len(self.sequence):
            raise AssertionError("SequenceSession exhausted")
        self.calls.append(url)
        action = self.sequence[index]

        if callable(action):
            return action(url, timeout)

        if isinstance(action, Exception):
            raise action

        return action


def test_process_source_stores_and_classifies_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 10
    instance.cutoff_date = datetime.utcnow() - timedelta(days=2)
    instance.storysniffer = object()

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]
            self.last_source: str | None = None

        def get_effective_discovery_methods(self, source_id: str):
            self.last_source = source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(kwargs)

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]

    existing_urls = {"https://existing.com/already"}

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda _self, _row, _meta: {"example.com", "existing.com"}
    )

    meta_updates: list[tuple[str, dict[str, Any]]] = []

    def fake_update_meta(
        self,
        source_id: str,
        updates: dict[str, Any],
    ) -> None:
        meta_updates.append((source_id, updates))

    instance._update_source_meta = _bind_method(instance, fake_update_meta)

    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)

    now = datetime.utcnow()

    rss_articles = [
        {
            "url": "https://example.com/news1",
            "publish_date": now.isoformat(),
            "metadata": {"feed_url": "https://example.com/feed"},
            "discovery_method": "rss_feed",
        },
        {
            "url": "https://existing.com/already",
            "publish_date": now.isoformat(),
        },
    ]

    rss_summary = {
        "feeds_tried": 1,
        "feeds_successful": 1,
        "network_errors": 0,
    }

    monkeypatch.setattr(
        instance,
        "discover_with_rss_feeds",
        _bind_method(
            instance,
            lambda _self, *_a, **_k: (rss_articles, rss_summary),
        ),
    )

    old_iso = (now - timedelta(days=5)).isoformat()

    monkeypatch.setattr(
        instance,
        "discover_with_newspaper4k",
        _bind_method(
            instance,
            lambda _self, *_a, **_k: [
                {
                    "url": "https://example.com/old",
                    "publish_date": old_iso,
                }
            ],
        ),
    )

    monkeypatch.setattr(
        instance,
        "discover_with_storysniffer",
        _bind_method(
            instance,
            lambda _self, *_a, **_k: [{"url": "https://other.com/outside"}],
        ),
    )

    store_calls: list[dict[str, Any]] = []

    class FakeDBManager:
        def __init__(
            self,
            *_a: Any,
            existing_records: dict[str, Any] | None = None,
            **_k: Any,
        ) -> None:
            self.session = _FakeSession()
            if existing_records:
                self.session._records.update(existing_records)

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    monkeypatch.setattr(discovery_module, "DatabaseManager", FakeDBManager)

    def _capture_upsert(_session: Any, **data: Any) -> None:
        store_calls.append(data)
        if isinstance(_session, _FakeSession):
            _session.add(types.SimpleNamespace(**data))
            _session.commit()

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        _capture_upsert,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "storysniffer",
            "rss_missing": "2000-01-01T00:00:00",
            "frequency": "daily",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-1",
            "name": "Source Alpha",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id="op-1",
    )

    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert result.articles_new == 1
    assert result.articles_duplicate == 1
    assert result.articles_expired == 1
    assert "storysniffer" in result.metadata["methods_attempted"]
    assert "rss_feed" in result.metadata["methods_attempted"]

    assert len(store_calls) == 1
    assert store_calls[0]["url"] == "https://example.com/news1"
    assert "publish_date" in store_calls[0]["meta"]

    assert "https://example.com/news1" in existing_urls

    assert telemetry.failures == []
    assert telemetry.last_source == "src-1"

    assert meta_updates
    updated = meta_updates[0][1]
    assert updated["last_successful_method"] == "rss_feed"


def test_source_processor_skips_rss_when_recently_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 5
    instance.cutoff_date = datetime.utcnow() - timedelta(days=7)
    instance.storysniffer = None  # type: ignore[attr-defined]

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]

        def get_effective_discovery_methods(self, source_id: str):
            del source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(kwargs)

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]
    instance.delay = 0
    instance.days_back = 7

    existing_urls: set[str] = set()

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._rss_retry_window_days = _bind_method(instance, lambda *_a, **_k: 2)

    rss_increments: list[Any] = []
    rss_resets: list[Any] = []

    instance._increment_rss_failure = _bind_method(
        instance, lambda *_a, **_k: rss_increments.append(1)
    )
    instance._reset_rss_failure_state = _bind_method(
        instance, lambda *_a, **_k: rss_resets.append(1)
    )

    def _raise_if_rss_invoked(*_a: Any, **_k: Any) -> None:
        raise AssertionError("RSS discovery should be skipped")

    instance.discover_with_rss_feeds = _bind_method(instance, _raise_if_rss_invoked)

    newspaper_calls: list[dict[str, Any]] = []

    def _fake_newspaper(
        _self: Any,
        *_a: Any,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        newspaper_calls.append(kwargs)
        return [
            {
                "url": "https://example.com/newspaper",
                "publish_date": datetime.utcnow().isoformat(),
                "discovery_method": "newspaper4k",
            }
        ]

    instance.discover_with_newspaper4k = _bind_method(instance, _fake_newspaper)

    instance.discover_with_storysniffer = _bind_method(instance, lambda *_a, **_k: [])

    meta_updates: list[tuple[str, dict[str, Any]]] = []

    instance._update_source_meta = _bind_method(
        instance,
        lambda _self, source_id, payload: meta_updates.append(
            (source_id, dict(payload))
        ),
    )

    store_calls: list[dict[str, Any]] = []

    class FakeDBManager:
        def __init__(
            self,
            *_a: Any,
            existing_records: dict[str, Any] | None = None,
            **_k: Any,
        ) -> None:
            self.session = _FakeSession()
            if existing_records:
                self.session._records.update(existing_records)

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    def _capture_upsert(_session: Any, **data: Any) -> None:
        store_calls.append(data)
        if isinstance(_session, _FakeSession):
            _session.add(types.SimpleNamespace(**data))
            _session.commit()

    monkeypatch.setattr(discovery_module, "DatabaseManager", FakeDBManager)
    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        _capture_upsert,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "rss_feed",
            "rss_missing": datetime.utcnow().isoformat(),
            "frequency": "daily",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-rss-skip",
            "name": "Skip RSS Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id="op-skip",
    )

    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert result.articles_new == 1
    assert "rss_feed" not in result.metadata["methods_attempted"]
    assert "newspaper4k" in result.metadata["methods_attempted"]

    assert newspaper_calls, "newspaper4k should run when RSS is skipped"
    assert newspaper_calls[0]["allow_build"] is False

    assert len(store_calls) == 1
    assert store_calls[0]["url"] == "https://example.com/newspaper"
    assert "https://example.com/newspaper" in existing_urls

    assert not rss_increments
    assert not rss_resets
    assert not meta_updates
    assert telemetry.failures == []


def test_source_processor_records_network_rss_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 3
    instance.cutoff_date = datetime.utcnow() - timedelta(days=3)
    instance.storysniffer = None  # type: ignore[attr-defined]
    instance.delay = 0
    instance.days_back = 7

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]

        def get_effective_discovery_methods(self, source_id: str):
            del source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(dict(kwargs))

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]

    existing_urls: set[str] = set()

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )

    meta_updates: list[tuple[str, dict[str, Any]]] = []

    instance._update_source_meta = _bind_method(
        instance,
        lambda _self, source_id, payload: meta_updates.append(
            (source_id, dict(payload))
        ),
    )

    instance.discover_with_rss_feeds = _bind_method(
        instance,
        lambda *_a, **_k: (_ for _ in ()).throw(
            requests.exceptions.Timeout("rss timed out")
        ),
    )

    class FakeDBManager:
        def __init__(self) -> None:
            self.session = _FakeSession()

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    instance._create_db_manager = _bind_method(
        instance, lambda *_a, **_k: FakeDBManager()
    )

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        lambda *_a, **_k: None,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "rss_feed",
            "frequency": "daily",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-rss-network",
            "name": "Network Failure Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id="op-network",
    )

    assert result.outcome == DiscoveryOutcome.NO_ARTICLES_FOUND
    assert result.metadata["methods_attempted"] == ["rss_feed", "newspaper4k"]

    assert telemetry.failures
    assert any(
        failure.get("discovery_method") == "rss" for failure in telemetry.failures
    )

    assert meta_updates
    meta_payload = meta_updates[-1][1]
    assert "rss_last_failed" in meta_payload
    assert "rss_missing" not in meta_payload


def test_source_processor_marks_rss_missing_after_non_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 3
    instance.cutoff_date = datetime.utcnow() - timedelta(days=3)
    instance.storysniffer = None  # type: ignore[attr-defined]
    instance.delay = 0
    instance.days_back = 7

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]

        def get_effective_discovery_methods(self, source_id: str):
            del source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(dict(kwargs))

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]

    existing_urls: set[str] = set()

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )

    meta_updates: list[tuple[str, dict[str, Any]]] = []

    instance._update_source_meta = _bind_method(
        instance,
        lambda _self, source_id, payload: meta_updates.append(
            (source_id, dict(payload))
        ),
    )

    instance.discover_with_rss_feeds = _bind_method(
        instance,
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rss parsing failed")),
    )

    instance.discover_with_newspaper4k = _bind_method(instance, lambda *_a, **_k: [])

    class FakeDBManager:
        def __init__(self) -> None:
            self.session = _FakeSession()

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    instance._create_db_manager = _bind_method(
        instance, lambda *_a, **_k: FakeDBManager()
    )

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        lambda *_a, **_k: None,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "rss_feed",
            "frequency": "daily",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-rss-missing",
            "name": "Missing RSS Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id="op-missing",
    )

    assert result.outcome == DiscoveryOutcome.NO_ARTICLES_FOUND
    assert result.metadata["methods_attempted"] == ["rss_feed", "newspaper4k"]

    assert telemetry.failures
    assert any(
        failure.get("discovery_method") == "rss" for failure in telemetry.failures
    )

    assert meta_updates
    meta_payload = meta_updates[-1][1]
    assert "rss_missing" in meta_payload
    assert "rss_last_failed" not in meta_payload


def test_source_processor_records_failures_for_downstream_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 5
    instance.cutoff_date = datetime.utcnow() - timedelta(days=5)
    instance.delay = 0
    instance.days_back = 7
    instance.storysniffer = object()

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
                DiscoveryMethod.STORYSNIFFER,
            ]

        def get_effective_discovery_methods(self, source_id: str):
            del source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(dict(kwargs))

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]

    existing_urls: set[str] = set()

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )

    instance.discover_with_rss_feeds = _bind_method(
        instance,
        lambda *_a, **_k: (
            [],
            {"feeds_tried": 1, "feeds_successful": 0, "network_errors": 0},
        ),
    )

    instance.discover_with_newspaper4k = _bind_method(
        instance,
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("newspaper down")),
    )

    instance.discover_with_storysniffer = _bind_method(
        instance,
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("storysniffer offline")),
    )

    class FakeDBManager:
        def __init__(self) -> None:
            self.session = _FakeSession()

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    instance._create_db_manager = _bind_method(
        instance, lambda *_a, **_k: FakeDBManager()
    )

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        lambda *_a, **_k: None,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "newspaper4k",
            "frequency": "weekly",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-downstream",
            "name": "Downstream Failure Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="weekly",
        operation_id="op-downstream",
    )

    assert result.outcome == DiscoveryOutcome.NO_ARTICLES_FOUND
    assert result.metadata["methods_attempted"] == [
        "rss_feed",
        "newspaper4k",
        "storysniffer",
    ]

    discovery_methods = {
        failure.get("discovery_method") for failure in telemetry.failures
    }
    assert {"newspaper4k", "storysniffer", "all_methods"}.issubset(discovery_methods)


def test_source_processor_skips_out_of_scope_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 5
    instance.cutoff_date = datetime.utcnow() - timedelta(days=4)
    instance.storysniffer = None  # type: ignore[attr-defined]
    instance.delay = 0
    instance.days_back = 7

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]

        def get_effective_discovery_methods(self, source_id: str):
            del source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(dict(kwargs))

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]

    existing_urls: set[str] = set()

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)

    meta_updates: list[tuple[str, dict[str, Any]]] = []

    instance._update_source_meta = _bind_method(
        instance,
        lambda _self, source_id, payload: meta_updates.append(
            (source_id, dict(payload))
        ),
    )

    discovered_articles = [
        {
            "url": "https://other.com/outside",
            "publish_date": datetime.utcnow().isoformat(),
            "discovery_method": "rss_feed",
        },
        {
            "url": "javascript:void(0)",
            "publish_date": datetime.utcnow().isoformat(),
            "discovery_method": "rss_feed",
        },
        {
            "url": "https://example.com/inside",
            "publish_date": datetime.utcnow().isoformat(),
            "discovery_method": "rss_feed",
        },
    ]

    instance.discover_with_rss_feeds = _bind_method(
        instance,
        lambda *_a, **_k: (
            discovered_articles,
            {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0},
        ),
    )

    instance.discover_with_newspaper4k = _bind_method(instance, lambda *_a, **_k: [])

    store_calls: list[dict[str, Any]] = []

    class FakeDBManager:
        def __init__(self) -> None:
            self.session = _FakeSession()

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    instance._create_db_manager = _bind_method(
        instance, lambda *_a, **_k: FakeDBManager()
    )

    def _capture_upsert(_session: Any, **data: Any) -> None:
        store_calls.append(data)
        if isinstance(_session, _FakeSession):
            _session.add(types.SimpleNamespace(**data))
            _session.commit()

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        _capture_upsert,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "rss_feed",
            "frequency": "daily",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-out-of-scope",
            "name": "Out of Scope Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id="op-scope",
    )

    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert result.articles_new == 1
    assert result.metadata["stored_count"] == 1
    assert result.metadata["out_of_scope_skipped"] == 2

    assert len(store_calls) == 1
    assert store_calls[0]["url"] == "https://example.com/inside"
    assert "rss_feed" in result.metadata["methods_attempted"]
    assert "https://example.com/inside" in existing_urls

    assert telemetry.failures == []
    assert meta_updates


def test_source_processor_stores_when_publish_date_parse_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 5
    instance.cutoff_date = datetime.utcnow() - timedelta(days=4)
    instance.storysniffer = None  # type: ignore[attr-defined]
    instance.delay = 0
    instance.days_back = 7

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [DiscoveryMethod.RSS_FEED]

        def get_effective_discovery_methods(self, source_id: str):
            del source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(dict(kwargs))

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]

    existing_urls: set[str] = set()

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)

    meta_updates: list[tuple[str, dict[str, Any]]] = []

    instance._update_source_meta = _bind_method(
        instance,
        lambda _self, source_id, payload: meta_updates.append(
            (source_id, dict(payload))
        ),
    )

    instance._coerce_publish_date = _bind_method(
        instance,
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad publish date")),
    )

    invalid_date = "Thu, 24 Oct 2024 18:42:00 GMT"

    instance.discover_with_rss_feeds = _bind_method(
        instance,
        lambda *_a, **_k: (
            [
                {
                    "url": "https://example.com/article",
                    "publish_date": invalid_date,
                    "metadata": {"feed": "primary"},
                    "discovery_method": "rss_feed",
                }
            ],
            {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0},
        ),
    )

    instance.discover_with_newspaper4k = _bind_method(instance, lambda *_a, **_k: [])

    store_calls: list[dict[str, Any]] = []

    class FakeDBManager:
        def __init__(self) -> None:
            self.session = _FakeSession()

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    instance._create_db_manager = _bind_method(
        instance, lambda *_a, **_k: FakeDBManager()
    )

    def _capture_upsert(_session: Any, **data: Any) -> None:
        store_calls.append(data)
        if isinstance(_session, _FakeSession):
            _session.add(types.SimpleNamespace(**data))
            _session.commit()

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        _capture_upsert,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "rss_feed",
            "frequency": "daily",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-publish-date",
            "name": "Publish Date Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id="op-publish",
    )

    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert result.articles_new == 1
    assert result.metadata["stored_count"] == 1
    assert result.metadata["methods_attempted"] == ["rss_feed"]

    assert len(store_calls) == 1
    stored = store_calls[0]
    assert stored["publish_date"] is None
    assert stored["meta"]["publish_date"] == invalid_date
    assert stored["meta"]["feed"] == "primary"
    assert "https://example.com/article" in existing_urls

    assert telemetry.failures == []
    assert meta_updates


def test_source_processor_continues_when_upsert_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 5
    instance.cutoff_date = datetime.utcnow() - timedelta(days=4)
    instance.storysniffer = None  # type: ignore[attr-defined]
    instance.delay = 0
    instance.days_back = 7

    class TelemetryStub:
        def __init__(self) -> None:
            self.failures: list[dict[str, Any]] = []
            self.methods = [DiscoveryMethod.RSS_FEED]

        def get_effective_discovery_methods(self, source_id: str):
            del source_id
            return list(self.methods)

        def record_site_failure(self, **kwargs: Any) -> None:
            self.failures.append(dict(kwargs))

    telemetry = TelemetryStub()
    instance.telemetry = telemetry  # type: ignore[assignment]

    existing_urls: set[str] = set()

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: existing_urls
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)

    instance.discover_with_rss_feeds = _bind_method(
        instance,
        lambda *_a, **_k: (
            [
                {
                    "url": "https://example.com/good",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
                {
                    "url": "https://example.com/bad",
                    "publish_date": datetime.utcnow().isoformat(),
                    "discovery_method": "rss_feed",
                },
            ],
            {"feeds_tried": 1, "feeds_successful": 1, "network_errors": 0},
        ),
    )

    store_calls: list[dict[str, Any]] = []

    class FakeDBManager:
        def __init__(self) -> None:
            self.session = _FakeSession()

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    instance._create_db_manager = _bind_method(
        instance, lambda *_a, **_k: FakeDBManager()
    )

    def _capture_upsert(_session: Any, **data: Any) -> None:
        if data["url"].endswith("bad"):
            raise RuntimeError("upsert failed")
        store_calls.append(data)
        if isinstance(_session, _FakeSession):
            _session.add(types.SimpleNamespace(**data))
            _session.commit()

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        _capture_upsert,
    )

    metadata_json = json.dumps(
        {
            "last_successful_method": "rss_feed",
            "frequency": "daily",
        }
    )

    source_row = pd.Series(
        {
            "id": "src-upsert-fail",
            "name": "Upsert Failure Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id="op-upsert",
    )

    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND
    assert result.articles_new == 2
    assert result.metadata["stored_count"] == 1
    assert result.metadata["methods_attempted"] == ["rss_feed"]

    assert len(store_calls) == 1
    assert store_calls[0]["url"] == "https://example.com/good"
    assert "https://example.com/good" in existing_urls
    assert "https://example.com/bad" not in existing_urls

    assert telemetry.failures == []


def test_process_source_dedupes_query_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    instance.database_url = "sqlite://"
    instance.max_articles_per_source = 5
    instance.cutoff_date = datetime.utcnow() - timedelta(days=2)
    instance.storysniffer = object()
    instance.telemetry = None  # type: ignore[assignment]
    instance.delay = 0
    instance.days_back = 7

    existing_urls = {"https://example.com/news-item"}

    instance._get_existing_urls_for_source = _bind_method(
        instance, lambda _self, _sid: set(existing_urls)
    )
    instance._collect_allowed_hosts = _bind_method(
        instance, lambda *_a, **_k: {"example.com"}
    )
    instance._reset_rss_failure_state = _bind_method(instance, lambda *_a, **_k: None)
    instance._increment_rss_failure = _bind_method(instance, lambda *_a, **_k: None)

    class FakeDBManager:
        def __init__(
            self,
            *_a: Any,
            existing_records: dict[str, Any] | None = None,
            **_k: Any,
        ) -> None:
            self.session = _FakeSession()
            if existing_records:
                self.session._records.update(existing_records)

        def __enter__(self) -> FakeDBManager:
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

    monkeypatch.setattr(discovery_module, "DatabaseManager", FakeDBManager)

    store_calls: list[dict[str, Any]] = []

    def fake_upsert(_session: Any, **data: Any) -> None:
        store_calls.append(data)
        if isinstance(_session, _FakeSession):
            _session.add(types.SimpleNamespace(**data))
            _session.commit()

    monkeypatch.setattr(
        "src.models.database.upsert_candidate_link",
        fake_upsert,
    )

    rss_summary = {
        "feeds_tried": 0,
        "feeds_successful": 0,
        "network_errors": 0,
    }

    monkeypatch.setattr(
        instance,
        "discover_with_rss_feeds",
        _bind_method(instance, lambda *_a, **_k: ([], rss_summary)),
    )
    monkeypatch.setattr(
        instance,
        "discover_with_newspaper4k",
        _bind_method(instance, lambda *_a, **_k: []),
    )

    dedupe_candidate = "https://example.com/news-item?utm=ref&utm_campaign=test#section"

    monkeypatch.setattr(
        instance,
        "discover_with_storysniffer",
        _bind_method(
            instance,
            lambda *_a, **_k: [
                {
                    "url": dedupe_candidate,
                    "discovery_method": "storysniffer",
                    "metadata": {},
                }
            ],
        ),
    )

    metadata_json = json.dumps({"frequency": "daily"})

    source_row = pd.Series(
        {
            "id": "src-query",
            "name": "Query Source",
            "url": "https://example.com",
            "metadata": metadata_json,
            "rss_feeds": json.dumps(["https://example.com/feed"]),
            "city": "Columbia",
            "county": "Boone",
            "type_classification": "local",
        }
    )

    result = instance.process_source(
        source_row,
        dataset_label="daily",
        operation_id=None,
    )

    assert result.outcome == DiscoveryOutcome.DUPLICATES_ONLY
    assert result.articles_new == 0
    assert result.articles_duplicate == 1
    assert store_calls == []


def test_run_discovery_processes_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    telemetry = _FakeTelemetry()
    instance.telemetry = telemetry  # type: ignore[assignment]
    instance.delay = 0
    instance.days_back = 7

    sources_df = pd.DataFrame(
        [
            {"id": "1", "name": "Source Alpha", "url": "https://alpha"},
            {"id": "2", "name": "Source Beta", "url": "https://beta"},
            {"id": "3", "name": "Source Gamma", "url": "https://gamma"},
            {"id": "4", "name": "Source Delta", "url": "https://delta"},
        ]
    )

    source_stats = {
        "sources_available": 4,
        "sources_due": 4,
        "sources_skipped": 0,
        "sources_limited_by_host": 2,
    }

    get_sources_calls: list[dict[str, Any]] = []

    def fake_get_sources_to_process(self, **kwargs: Any):
        get_sources_calls.append(kwargs)
        return sources_df.copy(), source_stats.copy()

    existing_counts = {
        "1": 0,
        "2": 5,
        "3": 0,
        "4": 0,
    }

    def fake_get_existing(self, source_id: str) -> int:
        return existing_counts[source_id]

    meta_updates: list[tuple[str, dict[str, Any]]] = []

    def fake_update_meta(
        self,
        source_id: str,
        updates: dict[str, Any],
    ) -> None:
        meta_updates.append((source_id, updates))

    def fake_process_source(self, source_row, dataset_label, operation_id):
        source_id = source_row["id"]
        if source_id == "1":
            return DiscoveryResult(
                outcome=DiscoveryOutcome.NEW_ARTICLES_FOUND,
                articles_found=3,
                articles_new=3,
            )
        if source_id == "3":
            return DiscoveryResult(
                outcome=DiscoveryOutcome.DUPLICATES_ONLY,
                articles_found=2,
                articles_new=0,
            )
        if source_id == "4":
            raise RuntimeError("boom")
        raise AssertionError(f"Unexpected source {source_id}")

    instance.get_sources_to_process = _bind_method(
        instance, fake_get_sources_to_process
    )
    instance._get_existing_article_count = _bind_method(instance, fake_get_existing)
    instance._update_source_meta = _bind_method(instance, fake_update_meta)
    instance.process_source = _bind_method(instance, fake_process_source)

    monkeypatch.setattr(discovery_module.time, "sleep", lambda *_a, **_k: None)

    stats = instance.run_discovery(
        dataset_label="daily",
        source_limit=4,
        source_filter="source",
        due_only=True,
        host_filter="example.com",
        city_filter="columbia",
        county_filter="boone",
        host_limit=2,
        existing_article_limit=3,
    )

    assert stats["sources_processed"] == 3
    assert stats["sources_succeeded"] == 2
    assert stats["sources_failed"] == 1
    assert stats["sources_with_content"] == 1
    assert stats["sources_no_content"] == 1
    assert stats["sources_skipped_existing"] == 1
    assert stats["total_candidates_discovered"] == 3
    assert stats["sources_available"] == 4
    assert stats["sources_limited_by_host"] == 2

    # Only source "1" gets metadata update because it has articles_new > 0
    # Source "3" returns DUPLICATES_ONLY (articles_new=0) so no update
    assert len(meta_updates) == 1
    updated_ids = {item[0] for item in meta_updates}
    assert updated_ids == {"1"}

    assert len(telemetry.outcomes) == 2
    assert len(telemetry.failures) == 1
    assert len(telemetry.tracker_updates) == 3

    call_kwargs = get_sources_calls[0]
    assert call_kwargs["due_only"] is True
    assert call_kwargs["host_filter"] == "example.com"
    assert call_kwargs["city_filter"] == "columbia"
    assert call_kwargs["county_filter"] == "boone"
    assert call_kwargs["host_limit"] == 2


def test_run_discovery_uuid_filter_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _make_discovery_stub()
    telemetry = _FakeTelemetry()
    instance.telemetry = telemetry  # type: ignore[assignment]
    instance.delay = 0
    instance.days_back = 7

    def fake_get_sources_to_process(self, **kwargs: Any):
        df = pd.DataFrame([{"id": "1", "name": "Source Alpha", "url": "https://alpha"}])
        return df, {"sources_available": 1}

    instance.get_sources_to_process = _bind_method(
        instance, fake_get_sources_to_process
    )

    monkeypatch.setattr(discovery_module.time, "sleep", lambda *_a, **_k: None)

    result = instance.run_discovery(source_uuids=["missing"])

    assert result == {
        "sources_processed": 0,
        "total_candidates_discovered": 0,
        "sources_failed": 0,
        "sources_succeeded": 0,
    }
    assert telemetry.outcomes == []
    assert telemetry.failures == []
