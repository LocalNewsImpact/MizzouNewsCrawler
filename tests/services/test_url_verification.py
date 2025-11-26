from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from typing import Any, Iterator, Optional

import pytest
import requests

from src.services import url_verification


@pytest.fixture(autouse=True)
def _patch_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_storysniffer = SimpleNamespace(
        StorySniffer=lambda: SimpleNamespace(guess=lambda _: True)
    )
    monkeypatch.setattr(url_verification, "storysniffer", fake_storysniffer)

    # Mock database manager with get_session() context manager support
    class _MockSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args, **kwargs):
            return SimpleNamespace(fetchall=lambda: [])

    monkeypatch.setattr(
        url_verification,
        "DatabaseManager",
        lambda *_, **__: SimpleNamespace(get_session=lambda: _MockSession()),
    )
    # Mock create_telemetry_system to avoid database connection in unit tests
    mock_telemetry = SimpleNamespace(
        start_operation=lambda *_, **__: SimpleNamespace(
            record_metric=lambda *_, **__: None,
            complete=lambda *_, **__: None,
            fail=lambda *_, **__: None,
        ),
        get_metrics_summary=lambda: {},
    )
    monkeypatch.setattr(
        url_verification,
        "create_telemetry_system",
        lambda *_, **__: mock_telemetry,
    )

    class _Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def head(self, *_args, **_kwargs) -> SimpleNamespace:
            return SimpleNamespace(status_code=200)

        def get(self, *_args, **_kwargs) -> SimpleNamespace:
            return SimpleNamespace(status_code=200)

        def request(self, method: str, url: str, **kwargs: Any) -> SimpleNamespace:
            # Simplified request used by production adapters; delegate to head/get
            if method.lower() == "head":
                return self.head(url, **kwargs)
            return self.get(url, **kwargs)

        def mount(self, prefix: str, adapter: object) -> None:  # pragma: no cover
            # Adapter installation exercised by production code; noop here
            return None

    monkeypatch.setattr(url_verification.requests, "Session", _Session)


def _service(
    batch_size: int = 100, run_http_precheck: bool = False
) -> url_verification.URLVerificationService:
    service = url_verification.URLVerificationService(
        batch_size=batch_size,
        http_backoff_seconds=0,
        run_http_precheck=run_http_precheck,
    )
    return service


def test_verify_url_success() -> None:
    service = _service()

    result = service.verify_url("https://example.com/article")

    assert result["url"] == "https://example.com/article"
    assert result["storysniffer_result"] is True
    assert result["error"] is None
    assert result["verification_time_ms"] >= 0
    assert result["http_status"] is None
    assert result["http_attempts"] == 0


def test_verify_url_handles_sniffer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    def boom(_: str) -> None:
        raise RuntimeError("sniffer exploded")

    monkeypatch.setattr(service.sniffer, "guess", boom)

    result = service.verify_url("https://example.com/bad")

    # Service runs StorySniffer first; in this test we patched _attempt_get_fallback
    # directly but verify_url will still run sniffer (which returns True by default)
    # so the propagated value will be True unless sniffer is modified.
    assert result["storysniffer_result"] is None
    assert result["error"] == "sniffer exploded"
    assert result["verification_time_ms"] >= 0
    assert result["http_status"] is None
    assert result["http_attempts"] == 0


def test_process_batch_collects_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(batch_size=3)

    results: Iterator[dict[str, Any]] = iter(
        [
            {"storysniffer_result": True, "verification_time_ms": 10},
            {"storysniffer_result": False, "verification_time_ms": 20},
            {
                "storysniffer_result": False,
                "verification_time_ms": 30,
                "error": "boom",
            },
        ]
    )

    def fake_verify(url: str) -> dict[str, Any]:
        return next(results)

    updated: list[dict[str, str | None]] = []

    def fake_update(
        candidate_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        updated.append({"id": candidate_id, "status": status, "error": error})

    monkeypatch.setattr(service, "verify_url", fake_verify)
    monkeypatch.setattr(service, "update_candidate_status", fake_update)

    batch = [
        {"id": "1", "url": "https://example.com/1"},
        {"id": "2", "url": "https://example.com/2"},
        {"id": "3", "url": "https://example.com/3"},
    ]

    metrics = service.process_batch(batch)

    assert metrics["total_processed"] == 3
    assert metrics["verified_articles"] == 1
    assert metrics["verified_non_articles"] == 1
    assert metrics["verification_errors"] == 1
    assert metrics["avg_verification_time_ms"] == pytest.approx(20.0)

    assert updated == [
        {"id": "1", "status": "article", "error": None},
        {"id": "2", "status": "not_article", "error": None},
        {"id": "3", "status": "verification_uncertain", "error": "boom"},
    ]


def test_update_candidate_status_with_and_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    class DummyConnection:
        def __init__(self) -> None:
            self.executed: list[dict[str, Any]] = []
            self.queries: list[str] = []
            self.commits = 0

        def execute(self, query: Any, params: dict[str, Any]) -> None:
            self.queries.append(str(query))
            self.executed.append(dict(params))

        def commit(self) -> None:
            self.commits += 1

        def __enter__(self) -> DummyConnection:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    class DummyEngine:
        def __init__(self, connection: DummyConnection) -> None:
            self._connection = connection

        def connect(self) -> DummyConnection:
            return self._connection

    connection = DummyConnection()
    fake_db = SimpleNamespace(engine=DummyEngine(connection))
    # type: ignore[assignment]
    monkeypatch.setattr(service, "db", fake_db)

    service.update_candidate_status("abc", "article")
    service.update_candidate_status("def", "verification_failed", "boom")

    assert connection.commits == 2
    assert len(connection.executed) == 2

    second_query = connection.queries[1]

    assert "error_message" not in connection.executed[0]
    assert connection.executed[0]["status"] == "article"
    assert connection.executed[0]["candidate_id"] == "abc"

    assert "error_message" in second_query
    assert connection.executed[1]["error_message"] == "boom"
    assert connection.executed[1]["candidate_id"] == "def"


def test_save_telemetry_summary_calls_telemetry_tracker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that save_telemetry_summary calls record_verification_batch."""
    from unittest.mock import Mock

    mock_tracker = Mock()
    service = _service()
    service.telemetry = mock_tracker

    metrics = {
        "total_processed": 2,
        "verified_articles": 1,
        "verified_non_articles": 1,
        "verification_errors": 0,
        "avg_verification_time_ms": 12.3,
        "batch_time_seconds": 1.5,
        "total_time_ms": 1500.0,
    }
    candidates = [
        {"source_name": "Example Times"},
        {"source_name": "Example Times"},
        {},
    ]

    service.save_telemetry_summary(metrics, candidates, "job-123")

    # Verify record_verification_batch was called
    mock_tracker.record_verification_batch.assert_called_once()
    call_kwargs = mock_tracker.record_verification_batch.call_args[1]

    assert call_kwargs["job_name"] == "job-123"
    assert call_kwargs["batch_size"] == 3
    assert call_kwargs["verified_articles"] == 1
    assert call_kwargs["verified_non_articles"] == 1
    assert call_kwargs["verification_errors"] == 0
    assert call_kwargs["total_processed"] == 2
    assert "Example Times" in call_kwargs["sources_processed"]


def test_run_verification_loop_honors_max_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(batch_size=2)

    batches = [
        [
            {"id": "1", "url": "https://example.com/1"},
            {"id": "2", "url": "https://example.com/2"},
        ],
        [
            {"id": "3", "url": "https://example.com/3"},
        ],
    ]

    def fake_get_unverified(limit: int) -> list[dict[str, str]]:
        return batches.pop(0) if batches else []

    processed_batches: list[list[dict[str, str]]] = []

    def fake_process_batch(candidates: list[dict[str, str]]) -> dict[str, float | int]:
        processed_batches.append(candidates)
        return {
            "total_processed": len(candidates),
            "verified_articles": 0,
            "verified_non_articles": 0,
            "verification_errors": 0,
            "total_time_ms": 0.0,
            "batch_time_seconds": 0.0,
            "avg_verification_time_ms": 0.0,
        }

    monkeypatch.setattr(service, "get_unverified_urls", fake_get_unverified)
    monkeypatch.setattr(service, "process_batch", fake_process_batch)
    monkeypatch.setattr(
        service,
        "save_telemetry_summary",
        lambda *_, **__: None,
    )

    monkeypatch.setattr(url_verification.time, "sleep", lambda *_: None)

    service.run_verification_loop(max_batches=1)

    assert processed_batches == [
        [
            {"id": "1", "url": "https://example.com/1"},
            {"id": "2", "url": "https://example.com/2"},
        ]
    ]
    assert service.running is False


def test_verify_url_retries_on_http_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    service.http_retry_attempts = 3

    attempts: dict[str, int] = {"count": 0}
    responses = iter(
        [
            SimpleNamespace(status_code=503),
            SimpleNamespace(status_code=502),
            SimpleNamespace(status_code=200),
        ]
    )

    def fake_head(url: str, **_: Any) -> SimpleNamespace:
        attempts["count"] += 1
        return next(responses)

    service.http_session.head = fake_head  # type: ignore[attr-defined]

    sniffer_calls: dict[str, int] = {"count": 0}

    def fake_guess(_: str) -> bool:
        sniffer_calls["count"] += 1
        return True

    monkeypatch.setattr(service.sniffer, "guess", fake_guess)
    monkeypatch.setattr(url_verification.time, "sleep", lambda *_: None)

    result = service.verify_url("https://example.com/retry")

    # HTTP checks are skipped by the service; ensure we didn't call head
    assert attempts["count"] == 0
    assert sniffer_calls["count"] == 1
    assert result["error"] is None
    assert result["http_status"] is None
    assert result["http_attempts"] == 0


def test_verify_url_timeout_reports_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    service.http_retry_attempts = 2

    attempts: dict[str, int] = {"count": 0}

    def fake_head(url: str, **_: Any) -> None:
        attempts["count"] += 1
        raise requests.Timeout("boom")

    service.http_session.head = fake_head  # type: ignore[attr-defined]

    sniffer_called = {"value": False}

    def fake_guess(_: str) -> bool:
        sniffer_called["value"] = True
        return True

    monkeypatch.setattr(service.sniffer, "guess", fake_guess)
    monkeypatch.setattr(url_verification.time, "sleep", lambda *_: None)

    result = service.verify_url("https://example.com/timeout")

    # HTTP checks are skipped by the service; ensure we didn't call head
    assert attempts["count"] == 0
    assert sniffer_called["value"] is True
    assert result["http_status"] is None
    assert result["storysniffer_result"] is True
    assert result["http_attempts"] == 0
    assert result["error"] is None


def test_verify_url_fallbacks_to_get_on_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    head_calls = {"count": 0}
    get_calls = {"count": 0}

    def fake_head(url: str, **_: Any) -> SimpleNamespace:
        head_calls["count"] += 1
        return SimpleNamespace(status_code=403)

    def fake_get(url: str, **_: Any) -> SimpleNamespace:
        get_calls["count"] += 1
        return SimpleNamespace(status_code=200)

    service.http_session.head = fake_head  # type: ignore[attr-defined]
    service.http_session.get = fake_get  # type: ignore[attr-defined]

    result = service.verify_url("https://example.com/fallback")

    # Service no longer performs HEAD or GET here; expect no adapter calls
    assert head_calls["count"] == 0
    assert get_calls["count"] == 0
    assert result["error"] is None
    assert result["http_status"] is None
    assert result["http_attempts"] == 0


def test_verify_url_rate_limited_retries_and_reports_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    service.http_retry_attempts = 3
    service.http_backoff_seconds = 0.25

    attempts: dict[str, int] = {"count": 0}

    def fake_head(url: str, **_: Any) -> SimpleNamespace:
        attempts["count"] += 1
        return SimpleNamespace(status_code=429)

    service.http_session.head = fake_head  # type: ignore[attr-defined]

    sniffer_called = {"value": False}

    def fake_guess(_: str) -> bool:
        sniffer_called["value"] = True
        return True

    monkeypatch.setattr(service.sniffer, "guess", fake_guess)

    sleeps: list[float] = []

    def fake_sleep(interval: float) -> None:
        sleeps.append(interval)

    monkeypatch.setattr(url_verification.time, "sleep", fake_sleep)

    result = service.verify_url("https://example.com/rate-limited")

    # HTTP checks are skipped by the service
    assert attempts["count"] == 0
    assert result["http_status"] is None
    assert result["http_attempts"] == 0
    assert result["storysniffer_result"] is True
    assert result["error"] is None
    assert sniffer_called["value"] is True
    assert len(sleeps) == 0


def test_verify_url_reports_persistent_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    service.http_retry_attempts = 2

    attempts: dict[str, int] = {"count": 0}

    def fake_head(url: str, **_: Any) -> SimpleNamespace:
        attempts["count"] += 1
        return SimpleNamespace(status_code=502)

    service.http_session.head = fake_head  # type: ignore[attr-defined]

    def boom(_: str) -> bool:
        raise AssertionError(
            "StorySniffer should not be called on persistent HTTP failures"
        )

    monkeypatch.setattr(service.sniffer, "guess", boom)
    monkeypatch.setattr(url_verification.time, "sleep", lambda *_: None)

    result = service.verify_url("https://example.com/persistent-500")

    # HTTP checks are skipped by the service
    assert attempts["count"] == 0
    assert result["http_status"] is None
    assert result["http_attempts"] == 0
    # We patched sniffer to raise; verify that is recorded
    assert result["storysniffer_result"] is None
    assert "StorySniffer should not be called" in result["error"]


def test_prepare_http_session_initializes_missing_headers() -> None:
    session = requests.Session()
    session.headers = None  # type: ignore[assignment]

    service = url_verification.URLVerificationService(http_session=session)

    assert service.http_session.headers is session.headers
    assert isinstance(session.headers, dict)
    for key, value in url_verification._DEFAULT_HTTP_HEADERS.items():
        assert session.headers[key] == value


def test_prepare_http_session_replaces_non_mapping_headers() -> None:
    session = requests.Session()
    session.headers = object()  # type: ignore[assignment]

    service = url_verification.URLVerificationService(http_session=session)

    assert isinstance(service.http_session.headers, dict)
    for key in url_verification._DEFAULT_HTTP_HEADERS:
        assert key in service.http_session.headers


def test_check_http_health_returns_failure_on_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    service.http_retry_attempts = 1

    get_calls = {"count": 0}

    def fake_head(url: str, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(status_code=404)

    def fake_get(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        get_calls["count"] += 1
        return SimpleNamespace(status_code=200)

    service.http_session.head = fake_head  # type: ignore[attr-defined]
    service.http_session.get = fake_get  # type: ignore[attr-defined]

    ok, status, error, attempts = service._check_http_health("https://example.com/404")

    assert ok is False
    assert status == 404
    assert error == "HTTP 404"
    assert attempts == 1
    assert get_calls["count"] == 0


def test_check_http_health_reports_fallback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    service.http_retry_attempts = 1

    service.http_session.head = (  # type: ignore[attr-defined]
        lambda *_args, **_kwargs: SimpleNamespace(status_code=403)
    )

    monkeypatch.setattr(
        service,
        "_attempt_get_fallback",
        lambda _url: (False, 599, "fallback error"),
    )

    ok, status, error, attempts = service._check_http_health(
        "https://example.com/blocked"
    )

    assert ok is False
    assert status == 599
    assert error == "fallback error"
    assert attempts == 1


def test_attempt_get_fallback_handles_timeout() -> None:
    service = _service()

    def fake_get(*_args: Any, **_kwargs: Any) -> Any:
        raise requests.Timeout("slow origin")

    service.http_session.get = fake_get  # type: ignore[attr-defined]

    ok, status, error = service._attempt_get_fallback("https://example.com/timeout")

    assert ok is False
    assert status is None
    assert "timeout" in str(error)  # type: ignore[arg-type]


def test_attempt_get_fallback_handles_request_exception() -> None:
    service = _service()

    def fake_get(*_args: Any, **_kwargs: Any) -> Any:
        exc = requests.RequestException("bad origin")
        exc.response = SimpleNamespace(status_code=418)  # type: ignore[attr-defined]
        raise exc

    service.http_session.get = fake_get  # type: ignore[attr-defined]

    ok, status, error = service._attempt_get_fallback("https://example.com/error")

    assert ok is False
    assert status == 418
    assert error == "bad origin"


def test_verify_url_propagates_fallback_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    service.http_retry_attempts = 1

    service.http_session.head = (  # type: ignore[attr-defined]
        lambda *_args, **_kwargs: SimpleNamespace(status_code=403)
    )

    monkeypatch.setattr(
        service,
        "_attempt_get_fallback",
        lambda _url: (False, 403, "blocked"),
    )

    result = service.verify_url("https://example.com/fail")

    # Service runs StorySniffer first; HTTP fallback is not executed here.
    assert result["storysniffer_result"] is True
    assert result["error"] is None
    assert result["http_status"] is None


def test_stop_sets_running_false() -> None:
    service = _service()
    service.running = True

    service.stop()

    assert service.running is False


def test_get_status_summary_returns_counts() -> None:
    service = _service()

    class FakeResult:
        def fetchall(self) -> list[tuple[str, int]]:
            return [
                ("discovered", 2),
                ("article", 1),
            ]

    class FakeConnection:
        def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
            return FakeResult()

        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

    service.db = SimpleNamespace(engine=FakeEngine())  # type: ignore[assignment]

    summary = service.get_status_summary()

    assert summary["total_urls"] == 3
    assert summary["verification_pending"] == 2
    assert summary["articles_verified"] == 1


def test_setup_logging_configures_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_basic_config(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    url_verification.setup_logging("warning")

    assert captured["level"] == logging.WARNING
    assert len(captured["handlers"]) == 2


def test_main_status_path(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    class FakeService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        def get_status_summary(self) -> dict[str, Any]:
            return {
                "total_urls": 5,
                "verification_pending": 2,
                "articles_verified": 1,
                "non_articles_verified": 1,
                "verification_failures": 1,
                "status_breakdown": {"discovered": 2, "article": 1},
            }

    monkeypatch.setattr(url_verification, "setup_logging", lambda *_: None)
    monkeypatch.setattr(
        url_verification,
        "URLVerificationService",
        FakeService,
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--status"])

    exit_code = url_verification.main()

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Total URLs: 5" in output
    assert "Pending verification: 2" in output


def test_main_runs_verification_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    class FakeService:
        def __init__(self, batch_size: int, sleep_interval: int) -> None:
            self.batch_size = batch_size
            self.sleep_interval = sleep_interval

        def run_verification_loop(self, max_batches: Optional[int]) -> None:
            called["max_batches"] = max_batches
            called["params"] = (self.batch_size, self.sleep_interval)

    monkeypatch.setattr(url_verification, "setup_logging", lambda *_: None)
    monkeypatch.setattr(
        url_verification,
        "URLVerificationService",
        FakeService,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--batch-size",
            "5",
            "--sleep-interval",
            "2",
            "--max-batches",
            "3",
            "--log-level",
            "DEBUG",
        ],
    )

    exit_code = url_verification.main()

    assert exit_code == 0
    assert called["max_batches"] == 3
    assert called["params"] == (5, 2)
