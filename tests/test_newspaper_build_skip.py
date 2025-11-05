import sys

sys.path.insert(0, ".")

from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from src.crawler import discovery  # noqa: E402
from src.crawler.discovery import NewsDiscovery  # noqa: E402


def test_newspaper_build_not_called_when_allow_build_false(monkeypatch):
    # Mock create_telemetry_system to avoid database connection
    mock_telemetry = SimpleNamespace(
        start_operation=lambda *_, **__: SimpleNamespace(
            record_metric=lambda *_, **__: None,
            complete=lambda *_, **__: None,
            fail=lambda *_, **__: None,
        ),
        get_metrics_summary=lambda: {},
    )
    monkeypatch.setattr(
        discovery,
        "create_telemetry_system",
        lambda *_, **__: mock_telemetry,
    )
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
