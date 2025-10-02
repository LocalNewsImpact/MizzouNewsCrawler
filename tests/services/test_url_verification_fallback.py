from __future__ import annotations

from typing import Optional, cast

import pytest
from requests import Session

import src.services.url_verification as url_verification


class _DummyResponse:
    def __init__(self, status_code: Optional[int]) -> None:
        self.status_code = status_code
        self._closed = False

    def close(self) -> None:  # pragma: no cover - defensive
        self._closed = True


class _DummySession:
    def __init__(
        self,
        *,
        head_status: Optional[int],
        get_status: Optional[int],
    ) -> None:
        self._head_status = head_status
        self._get_status = get_status
        self.headers: dict[str, str] = {}
        self.head_count = 0
        self.get_count = 0

    def head(self, url: str, allow_redirects: bool, timeout: float):
        self.head_count += 1
        return _DummyResponse(self._head_status)

    def get(
        self,
        url: str,
        allow_redirects: bool,
        timeout: float,
        stream: bool,
    ):
        self.get_count += 1
        return _DummyResponse(self._get_status)


class _DummySniffer:
    def __init__(self, *, result: bool) -> None:
        self.result = result
        self.calls: list[str] = []

    def guess(self, url: str) -> bool:
        self.calls.append(url)
        return self.result


class _StubDatabaseManager:
    def __init__(self) -> None:
        self.engine = None
        self.session = None


@pytest.fixture
def service_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        url_verification,
        "DatabaseManager",
        lambda: _StubDatabaseManager(),
    )

    def factory(
        session: _DummySession,
        *,
        sniffer_result: bool = True,
    ) -> url_verification.URLVerificationService:
        service = url_verification.URLVerificationService(
            http_session=cast(Session, session),
            http_retry_attempts=1,
            http_backoff_seconds=0,
        )
        service.sniffer = _DummySniffer(result=sniffer_result)
        return service

    return factory


def test_verify_url_falls_back_to_get_when_head_blocked(service_factory) -> None:
    session = _DummySession(head_status=403, get_status=200)
    service = service_factory(session)

    result = service.verify_url("https://example.com/article")

    assert session.head_count == 1
    assert session.get_count == 1
    assert result["error"] is None
    assert result["http_status"] == 200
    assert result["storysniffer_result"] is True
    assert service.sniffer.calls == ["https://example.com/article"]


def test_verify_url_reports_error_when_fallback_fails(service_factory) -> None:
    session = _DummySession(head_status=403, get_status=403)
    service = service_factory(session)

    result = service.verify_url("https://example.com/article")

    assert session.head_count == 1
    assert session.get_count == 1
    assert result["error"] == "HTTP 403"
    assert result["http_status"] == 403
    assert result["storysniffer_result"] is None
    assert service.sniffer.calls == []
