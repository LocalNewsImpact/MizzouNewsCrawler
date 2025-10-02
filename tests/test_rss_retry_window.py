import pathlib
import sys

# Ensure project root on sys.path
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.crawler.discovery import NewsDiscovery  # noqa: E402


@pytest.mark.parametrize(
    "frequency,expected",
    [
        ("daily", 2),
        ("weekly", 7),
        ("monthly", 7),
        (None, 7),
        ("broadcast", 2),
    ],
)
def test_rss_retry_window_days(frequency, expected):
    discovery = NewsDiscovery(database_url="sqlite:///:memory:")
    assert discovery._rss_retry_window_days(frequency) == expected
