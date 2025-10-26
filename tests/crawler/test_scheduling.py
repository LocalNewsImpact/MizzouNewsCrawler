from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional

import pytest

import src.crawler.scheduling as scheduling

# Import kept for historical reference; tests use duck-typed _Database fixtures
# Tests use duck-typed _Database and dummy objects; keep type-ignores on call sites.


@pytest.mark.parametrize(
    "freq, expected",
    [
        (None, 7),
        ("", 7),
        ("Daily updates", 0.25),
        ("Broadcast", 0.25),
        ("Bi-weekly", 14),
        ("Weekly", 7),
        ("Triweekly", 7),
        ("Monthly", 30),
        ("Hourly", 1),
        ("Other", 7),
    ],
)
def test_parse_frequency_to_days(freq, expected):
    assert scheduling.parse_frequency_to_days(freq) == expected


class _Connection:
    def __init__(self, rows, *, raises: Optional[Exception] = None):
        self.rows = rows
        self.raises = raises
        self.executed_sql = None
        self.executed_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        if self.raises:
            raise self.raises
        self.executed_sql = sql
        self.executed_params = params
        return self

    def fetchone(self):
        return self.rows


class _Database:
    def __init__(self, connection: _Connection):
        self.engine = SimpleNamespace(connect=lambda: connection)


def test_get_last_processed_date_returns_datetime():
    last = datetime(2025, 9, 1, 12, 0, 0)
    connection = _Connection((last,))
    db = _Database(connection)  # type: ignore[assignment]

    result = scheduling._get_last_processed_date(
        db, "source-1"
    )  # type: ignore[arg-type]

    assert result == last
    assert connection.executed_params == {"sid": "source-1"}


def test_get_last_processed_date_parses_iso_string():
    connection = _Connection(("2025-09-01T12:00:00",))
    db = _Database(connection)  # type: ignore[assignment]

    result = scheduling._get_last_processed_date(db, "abc")  # type: ignore[arg-type]

    assert isinstance(result, datetime)
    assert result.isoformat() == "2025-09-01T12:00:00"


@pytest.mark.parametrize(
    "db_rows",
    [None, (None,), ()],
)
def test_get_last_processed_date_handles_missing_rows(db_rows):
    connection = _Connection(db_rows)
    db = _Database(connection)  # type: ignore[assignment]

    assert (
        scheduling._get_last_processed_date(db, "sid") is None  # type: ignore[arg-type]
    )


def test_get_last_processed_date_swallows_errors():
    connection = _Connection((None,), raises=RuntimeError("boom"))
    db = _Database(connection)  # type: ignore[assignment]

    assert scheduling._get_last_processed_date(db, "sid") is None


def test_should_schedule_discovery_returns_true_without_history(monkeypatch):
    monkeypatch.setattr(
        scheduling,
        "_get_last_processed_date",
        lambda _db, _sid: None,
    )

    dummy_db = object()  # type: ignore[assignment]
    assert (
        scheduling.should_schedule_discovery(  # type: ignore[arg-type]
            dummy_db, "123", {}
        )
        is True
    )


def test_should_schedule_discovery_uses_last_discovery_timestamp(monkeypatch):
    monkeypatch.setattr(
        scheduling,
        "_get_last_processed_date",
        lambda _db, _sid: None,
    )
    now = datetime(2025, 9, 30, 12, 0, 0)
    source_meta = {"last_discovery_at": "2025-09-10T00:00:00"}

    dummy_db = object()  # type: ignore[assignment]
    assert scheduling.should_schedule_discovery(
        dummy_db,  # type: ignore[arg-type]
        "123",
        source_meta,
        now,
    )


def test_should_schedule_discovery_respects_cadence(monkeypatch):
    now = datetime(2025, 9, 30, 12, 0, 0)
    last_processed = now - timedelta(days=8)
    monkeypatch.setattr(
        scheduling,
        "_get_last_processed_date",
        lambda _db, _sid: last_processed,
    )

    dummy_db = object()  # type: ignore[assignment]
    assert scheduling.should_schedule_discovery(
        dummy_db,  # type: ignore[arg-type]
        "123",
        {"frequency": "weekly"},
        now,
    )


def test_should_schedule_discovery_returns_false_when_not_due(monkeypatch):
    now = datetime(2025, 9, 30, 12, 0, 0)
    last_processed = now - timedelta(hours=1)
    monkeypatch.setattr(
        scheduling,
        "_get_last_processed_date",
        lambda _db, _sid: last_processed,
    )

    assert (
        scheduling.should_schedule_discovery(
            object(),  # type: ignore[arg-type]
            "123",
            {"frequency": "hourly"},
            now,
        )
        is False
    )


def test_should_schedule_discovery_handles_bad_meta(monkeypatch):
    now = datetime(2025, 9, 30, 12, 0, 0)
    last_processed = now - timedelta(days=10)
    monkeypatch.setattr(
        scheduling,
        "_get_last_processed_date",
        lambda _db, _sid: last_processed,
    )

    bad_meta = 42  # type: ignore[assignment]
    dummy_db = object()  # type: ignore[assignment]

    assert scheduling.should_schedule_discovery(
        dummy_db,  # type: ignore[arg-type]
        "123",
        bad_meta,  # type: ignore[arg-type]
        now,
    )
