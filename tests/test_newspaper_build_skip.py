import sys
from datetime import datetime

sys.path.insert(0, ".")

from src.crawler.discovery import NewsDiscovery


def test_newspaper_build_not_called_when_allow_build_false(monkeypatch):
    nd = NewsDiscovery(timeout=5, delay=0)

    # If newspaper.build gets called, fail the test
    def _build_fail(*args, **kwargs):
        raise AssertionError("newspaper.build should not be called")

    monkeypatch.setattr("newspaper.build", _build_fail)

    # Call discover_with_newspaper4k with allow_build=False and rss_missing
    res = nd.discover_with_newspaper4k(
        "https://www.417mag.com",
        source_id=None,
        operation_id=None,
        source_meta={"rss_missing": datetime.utcnow().isoformat()},
        allow_build=False,
    )

    assert isinstance(res, list)
