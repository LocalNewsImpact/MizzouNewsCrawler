import pathlib
import sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.crawler.discovery import RSS_MISSING_THRESHOLD, NewsDiscovery  # noqa: E402
from src.models import Source  # noqa: E402
from src.models.database import DatabaseManager  # noqa: E402
from tests.helpers.source_state import read_source_state  # noqa: E402


def test_repeated_non_network_failures_set_rss_missing(tmp_path, monkeypatch):
    """After RSS_MISSING_THRESHOLD non-network failures, rss_missing_at is set.

    Uses a real temporary SQLite database to exercise typed column logic
    instead of mocking metadata. This avoids reliance on legacy JSON updates.
    """
    db_file = tmp_path / "rss_missing_thresh.db"
    db_url = f"sqlite:///{db_file}"

    # Seed source row
    dbm = DatabaseManager(database_url=db_url)
    src = Source(
        id="test-source-2",
        host="example.com",
        host_norm="example.com",
        canonical_name="Example",
        meta={},
    )
    dbm.session.add(src)
    dbm.session.commit()
    dbm.close()

    discovery = NewsDiscovery(database_url=db_url, timeout=1, delay=0)

    # Simulate non-network RSS failures
    def fake_rss(*args, **kwargs):
        return ([], {"feeds_tried": 1, "feeds_successful": 0, "network_errors": 0})

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", fake_rss)
    monkeypatch.setattr(discovery, "discover_with_newspaper4k", lambda *a, **k: [])
    monkeypatch.setattr(discovery, "discover_with_storysniffer", lambda *a, **k: [])

    source_row = pd.Series(
        {
            "id": "test-source-2",
            "url": "https://example.com",
            "name": "Example",
            "metadata": "{}",
        }
    )

    # Execute failures up to threshold
    for i in range(RSS_MISSING_THRESHOLD):
        discovery.process_source(source_row, dataset_label=None, operation_id=None)
        state = read_source_state(DatabaseManager(db_url).engine, "test-source-2")
        assert state.get("rss_consecutive_failures", 0) == i + 1

    # After threshold, missing should be set
    final_state = read_source_state(DatabaseManager(db_url).engine, "test-source-2")
    assert final_state.get("rss_missing_at") is not None, (
        "rss_missing_at was not set after repeated non-network failures"
    )
