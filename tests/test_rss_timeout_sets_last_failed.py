import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.crawler.discovery import NewsDiscovery  # noqa: E402
from src.models import Source  # noqa: E402
from src.models.database import DatabaseManager  # noqa: E402
from tests.helpers.source_state import read_source_state  # noqa: E402


def test_timeout_records_rss_last_failed(tmp_path, monkeypatch):
    """Network (transient) errors set rss_last_failed_at but do not mark missing.

    Migrated to typed column assertions instead of inspecting legacy metadata updates.
    """
    db_file = tmp_path / "timeout_last_failed.db"
    db_url = f"sqlite:///{db_file}"

    # Seed source row
    dbm = DatabaseManager(database_url=db_url)
    src = Source(
        id="test-source-1",
        host="example.com",
        host_norm="example.com",
        canonical_name="Example",
        meta={},
    )
    dbm.session.add(src)
    dbm.session.commit()
    dbm.close()

    nd = NewsDiscovery(database_url=db_url, timeout=1, delay=0)

    # Simulate network error (network_errors=1)
    def fake_rss(*args, **kwargs):
        return ([], {"feeds_tried": 1, "feeds_successful": 0, "network_errors": 1})

    monkeypatch.setattr(nd, "discover_with_rss_feeds", fake_rss)
    monkeypatch.setattr(nd, "discover_with_newspaper4k", lambda *a, **k: [])
    monkeypatch.setattr(nd, "discover_with_storysniffer", lambda *a, **k: [])

    source_row = pd.Series(
        {
            "id": "test-source-1",
            "url": "https://example.com",
            "name": "Example",
            "metadata": "{}",
        }
    )

    nd.process_source(source_row, dataset_label=None, operation_id=None)

    state = read_source_state(DatabaseManager(db_url).engine, "test-source-1")

    assert state.get("rss_last_failed_at") is not None, "Expected last_failed timestamp"
    assert state.get("rss_missing_at") is None, "rss_missing_at should not be set"
    assert state.get("rss_consecutive_failures", 0) == 0, "Network errors reset counter"
