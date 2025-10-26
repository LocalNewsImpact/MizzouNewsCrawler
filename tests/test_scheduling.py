import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repository root is on sys.path for imports during tests
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.crawler.scheduling import (  # noqa: E402
    parse_frequency_to_days,
    should_schedule_discovery,
)
from src.models.database import DatabaseManager  # noqa: E402


def test_parse_frequency_daily():
    assert parse_frequency_to_days("daily") == 0.25
    assert parse_frequency_to_days("Daily") == 0.25


def test_parse_frequency_broadcast():
    assert parse_frequency_to_days("broadcast station") == 0.25
    assert parse_frequency_to_days("Video_Broadcast") == 0.25


def test_parse_frequency_weekly():
    assert parse_frequency_to_days("weekly") == 7
    assert parse_frequency_to_days("every week") == 7


def test_parse_frequency_biweekly():
    assert parse_frequency_to_days("bi-weekly") == 14
    assert parse_frequency_to_days("biweekly") == 14


def test_parse_frequency_monthly():
    assert parse_frequency_to_days("monthly") == 30


def test_parse_frequency_unknown():
    # Unknown strings fall back to default 7 days
    assert parse_frequency_to_days(None) == 7
    assert parse_frequency_to_days("") == 7
    assert parse_frequency_to_days("sometimes") == 7


def test_should_schedule_discovery_daily_respects_12_hour_window():
    now = datetime(2025, 9, 28, 12, 0, 0)
    # Daily cadence is now 6 hours (0.25 days); test should NOT schedule
    # if less than 6 hours has passed
    three_hours_ago = now - timedelta(hours=3)
    patch_target = "src.crawler.scheduling._get_last_processed_date"
    with DatabaseManager("sqlite:///:memory:") as db:
        with patch(patch_target, return_value=three_hours_ago):
            assert not should_schedule_discovery(
                db,
                "source-1",
                {"frequency": "daily"},
                now=now,
            )

        seven_hours_ago = now - timedelta(hours=7)
        with patch(patch_target, return_value=seven_hours_ago):
            assert should_schedule_discovery(
                db,
                "source-1",
                {"frequency": "daily"},
                now=now,
            )


def test_should_schedule_discovery_broadcast_uses_12_hour_window():
    now = datetime(2025, 9, 28, 12, 0, 0)
    # Broadcast cadence is now 6 hours (0.25 days)
    five_hours_ago = now - timedelta(hours=5)
    patch_target = "src.crawler.scheduling._get_last_processed_date"
    with DatabaseManager("sqlite:///:memory:") as db:
        with patch(patch_target, return_value=five_hours_ago):
            assert not should_schedule_discovery(
                db,
                "source-1",
                {"frequency": "broadcast"},
                now=now,
            )


@pytest.mark.parametrize(
    "frequency,delta_hours,expected",
    [
        ("weekly", 24 * 6, False),
        ("weekly", 24 * 8, True),
        ("monthly", 24 * 20, False),
        ("monthly", 24 * 35, True),
        (None, 24 * 5, False),
        (None, 24 * 9, True),
    ],
)
def test_should_schedule_discovery_frequency_matrix(
    frequency,
    delta_hours,
    expected,
):
    now = datetime(2025, 9, 28, 12, 0, 0)
    last_processed = now - timedelta(hours=delta_hours)
    patch_target = "src.crawler.scheduling._get_last_processed_date"
    with DatabaseManager("sqlite:///:memory:") as db:
        with patch(patch_target, return_value=last_processed):
            assert (
                should_schedule_discovery(
                    db,
                    "source-1",
                    {"frequency": frequency} if frequency else {},
                    now=now,
                )
                is expected
            )


def test_should_schedule_discovery_uses_metadata_when_no_processed_rows():
    now = datetime(2025, 9, 28, 12, 0, 0)
    eight_days_ago = (now - timedelta(days=8)).isoformat()
    two_days_ago = (now - timedelta(days=2)).isoformat()
    patch_target = "src.crawler.scheduling._get_last_processed_date"
    with DatabaseManager("sqlite:///:memory:") as db:
        with patch(patch_target, return_value=None):
            assert should_schedule_discovery(
                db,
                "source-1",
                {"frequency": "weekly", "last_discovery_at": eight_days_ago},
                now=now,
            )
            assert not should_schedule_discovery(
                db,
                "source-1",
                {"frequency": "weekly", "last_discovery_at": two_days_ago},
                now=now,
            )


def test_should_schedule_discovery_handles_invalid_last_discovery_metadata():
    now = datetime(2025, 9, 28, 12, 0, 0)
    patch_target = "src.crawler.scheduling._get_last_processed_date"
    with DatabaseManager("sqlite:///:memory:") as db:
        with patch(patch_target, return_value=None):
            assert should_schedule_discovery(
                db,
                "source-1",
                {"frequency": "weekly", "last_discovery_at": "not-a-date"},
                now=now,
            )

        with patch(
            patch_target,
            return_value=now - timedelta(hours=12),
        ):
            assert should_schedule_discovery(
                db,
                "source-1",
                {"frequency": "broadcast"},
                now=now,
            )
