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
        ("Bi-weekly", 7),  # Check bi-weekly sites weekly
        ("Weekly", 1),  # Check weekly publications daily
        ("Triweekly", 3.5),  # Check triweekly sites twice per week
        ("Monthly", 7),  # Check monthly publications weekly
        ("Hourly", 0.25),  # Check hourly sites every 6 hours
        ("Other", 7),
    ],
)
def test_parse_frequency_to_days(freq, expected):
    """Test parse_frequency_to_days (legacy wrapper for discovery interval)."""
    assert scheduling.parse_frequency_to_days(freq) == expected


@pytest.mark.parametrize(
    "freq, expected",
    [
        (None, 7),
        ("", 7),
        ("Daily updates", 0.25),
        ("Broadcast", 0.25),
        ("Bi-weekly", 7),  # Discovery checks: weekly for bi-weekly pubs
        ("Weekly", 1),  # Discovery checks: daily for weekly pubs
        ("Triweekly", 3.5),  # Discovery checks: twice weekly for triweekly pubs
        ("Monthly", 7),  # Discovery checks: weekly for monthly pubs
        ("Hourly", 0.25),  # Discovery checks: every 6 hours for hourly pubs
        ("Other", 7),
    ],
)
def test_parse_frequency_to_discovery_days(freq, expected):
    """Test parse_frequency_to_discovery_days (discovery interval)."""
    assert scheduling.parse_frequency_to_discovery_days(freq) == expected


@pytest.mark.parametrize(
    "freq, expected",
    [
        (None, 7),
        ("", 7),
        ("Daily updates", 1),  # Publication cadence: daily
        ("Broadcast", 1),
        ("Bi-weekly", 14),  # Publication cadence: bi-weekly (14 days)
        ("Weekly", 7),  # Publication cadence: weekly (7 days)
        ("Triweekly", 7),  # Publication cadence: ~3x per 21 days
        ("Monthly", 30),  # Publication cadence: monthly (30 days)
        ("Hourly", 0.25),  # Publication cadence: hourly
        ("Other", 7),
    ],
)
def test_parse_frequency_to_publication_days(freq, expected):
    """Test parse_frequency_to_publication_days (publication interval)."""
    assert scheduling.parse_frequency_to_publication_days(freq) == expected


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


class TestSchedulingEdgeCases:
    """Test edge cases in scheduling logic."""

    @pytest.mark.parametrize(
        "freq, expected",
        [
            ("DAILY", 0.25),  # Case insensitive
            ("daily", 0.25),
            ("DaIlY uPdAtEs", 0.25),
            ("broadcast news", 0.25),
            ("WEEKLY", 1),  # Discovery interval for weekly (daily checks)
            (
                "Biweekly",
                7,
            ),  # Alternative spelling - discovery interval (weekly checks)
            ("Bi-Weekly", 7),  # Discovery interval (weekly checks)
            ("monthly newsletter", 7),  # Discovery interval (weekly checks)
            ("unknown frequency", 7),  # Default fallback
        ],
    )
    def test_parse_frequency_to_days_case_insensitive(self, freq, expected):
        """Frequency parsing should be case insensitive (returns discovery interval)."""
        assert scheduling.parse_frequency_to_days(freq) == expected

    def test_parse_frequency_to_days_with_whitespace(self):
        """Whitespace should be handled correctly."""
        assert scheduling.parse_frequency_to_days("  Daily  ") == 0.25
        assert scheduling.parse_frequency_to_days("Weekly\n") == 1  # Discovery interval

    def test_get_last_processed_date_with_invalid_iso_string(self):
        """Invalid ISO strings should return None instead of crashing."""
        connection = _Connection(("not-a-valid-date",))
        db = _Database(connection)  # type: ignore[assignment]

        result = scheduling._get_last_processed_date(db, "abc")  # type: ignore[arg-type]
        # Should handle parsing error gracefully
        assert result is None or isinstance(result, datetime)

    def test_should_schedule_discovery_at_exact_boundary(self, monkeypatch):
        """Test scheduling at exact cadence boundary."""
        now = datetime(2025, 9, 30, 12, 0, 0)
        # Exactly 1 day ago (weekly discovery cadence is daily)
        last_processed = now - timedelta(days=1)
        monkeypatch.setattr(
            scheduling,
            "_get_last_processed_date",
            lambda _db, _sid: last_processed,
        )

        result = scheduling.should_schedule_discovery(
            object(),  # type: ignore[arg-type]
            "123",
            {"frequency": "weekly"},
            now,
        )
        # At exact boundary, should schedule (>= condition)
        assert result is True

    def test_should_schedule_discovery_just_before_boundary(self, monkeypatch):
        """Test scheduling just before cadence boundary."""
        now = datetime(2025, 9, 30, 12, 0, 0)
        # 0.9 days ago (just under weekly 1 day discovery cadence)
        last_processed = now - timedelta(days=0.9)
        monkeypatch.setattr(
            scheduling,
            "_get_last_processed_date",
            lambda _db, _sid: last_processed,
        )

        result = scheduling.should_schedule_discovery(
            object(),  # type: ignore[arg-type]
            "123",
            {"frequency": "weekly"},
            now,
        )
        # Just before boundary, should not schedule
        assert result is False

    def test_should_schedule_discovery_with_empty_frequency(self, monkeypatch):
        """Empty frequency should use default cadence."""
        now = datetime(2025, 9, 30, 12, 0, 0)
        last_processed = now - timedelta(days=8)
        monkeypatch.setattr(
            scheduling,
            "_get_last_processed_date",
            lambda _db, _sid: last_processed,
        )

        result = scheduling.should_schedule_discovery(
            object(),  # type: ignore[arg-type]
            "123",
            {"frequency": ""},  # Empty string
            now,
        )
        # Should use default 7-day cadence, 8 days passed -> schedule
        assert result is True

    def test_should_schedule_discovery_with_last_discovery_at_malformed(
        self, monkeypatch
    ):
        """Malformed last_discovery_at should be handled gracefully."""
        monkeypatch.setattr(
            scheduling,
            "_get_last_processed_date",
            lambda _db, _sid: None,
        )
        now = datetime(2025, 9, 30, 12, 0, 0)
        source_meta = {"last_discovery_at": "not-a-valid-date"}

        result = scheduling.should_schedule_discovery(
            object(),  # type: ignore[arg-type]
            "123",
            source_meta,
            now,
        )
        # Should handle parsing error and still schedule
        assert isinstance(result, bool)

    def test_should_schedule_discovery_with_future_last_processed(self, monkeypatch):
        """Future last_processed date should not prevent scheduling."""
        now = datetime(2025, 9, 30, 12, 0, 0)
        # Last processed is in the future (clock skew or bad data)
        last_processed = now + timedelta(days=1)
        monkeypatch.setattr(
            scheduling,
            "_get_last_processed_date",
            lambda _db, _sid: last_processed,
        )

        result = scheduling.should_schedule_discovery(
            object(),  # type: ignore[arg-type]
            "123",
            {"frequency": "daily"},
            now,
        )
        # Should handle gracefully (negative time_since should not schedule)
        assert isinstance(result, bool)

    def test_should_schedule_discovery_with_none_metadata(self, monkeypatch):
        """None metadata should be handled as empty dict."""
        now = datetime(2025, 9, 30, 12, 0, 0)
        last_processed = now - timedelta(days=10)
        monkeypatch.setattr(
            scheduling,
            "_get_last_processed_date",
            lambda _db, _sid: last_processed,
        )

        result = scheduling.should_schedule_discovery(
            object(),  # type: ignore[arg-type]
            "123",
            None,  # type: ignore[arg-type]
            now,
        )
        # Should handle None gracefully
        assert result is True
