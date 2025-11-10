import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crawler.discovery import RSS_MISSING_THRESHOLD, NewsDiscovery  # noqa: E402
from src.models import Source  # noqa: E402
from src.models.database import DatabaseManager  # noqa: E402
from tests.helpers.source_state import read_source_state  # noqa: E402


def test_consecutive_non_network_failures(tmp_path, monkeypatch):
    db_file = tmp_path / "test_mizzou_fail.db"
    db_url = f"sqlite:///{db_file}"

    # Create a source row in DB
    dbm_init = DatabaseManager(database_url=db_url)
    s = Source(
        id="fail-source",
        host="example.org",
        host_norm="example.org",
        canonical_name="Fail Source",
        meta={},
    )
    dbm_init.session.add(s)
    dbm_init.session.commit()
    dbm_init.close()

    discovery = NewsDiscovery(database_url=db_url)

    # Prepare a pandas Series to pass into process_source
    src = pd.Series(
        {
            "id": "fail-source",
            "name": "Fail Source",
            "url": "https://example.org",
            "metadata": json.dumps({}),
        }
    )

    # Monkeypatch discover_with_rss_feeds to simulate non-network failure
    def rss_non_network(*a, **k):
        return [], {"feeds_tried": 1, "feeds_successful": 0, "network_errors": 0}

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", rss_non_network)

    # Run process_source RSS_MISSING_THRESHOLD times, asserting increment
    for i in range(RSS_MISSING_THRESHOLD):
        discovery.process_source(src, dataset_label="test", operation_id=None)
        state = read_source_state(DatabaseManager(db_url).engine, "fail-source")
        expected = i + 1
        assert state.get("rss_consecutive_failures", 0) == expected

    # After threshold, rss_missing_at should be set
    state = read_source_state(DatabaseManager(db_url).engine, "fail-source")
    assert state.get("rss_missing_at") is not None


def test_network_error_resets_counter(tmp_path, monkeypatch):
    db_file = tmp_path / "test_mizzou_net.db"
    db_url = f"sqlite:///{db_file}"

    dbm_init = DatabaseManager(database_url=db_url)
    s = Source(
        id="net-source",
        host="example.net",
        host_norm="example.net",
        canonical_name="Net Source",
        meta={"rss_consecutive_failures": 2},
    )
    dbm_init.session.add(s)
    dbm_init.session.commit()
    dbm_init.close()

    discovery = NewsDiscovery(database_url=db_url)

    src = pd.Series(
        {
            "id": "net-source",
            "name": "Net Source",
            "url": "https://example.net",
            "metadata": json.dumps({"rss_consecutive_failures": 2}),
        }
    )

    # Simulate a network error (timeout)
    def rss_network_error(*a, **k):
        return [], {"feeds_tried": 1, "feeds_successful": 0, "network_errors": 1}

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", rss_network_error)

    discovery.process_source(src, dataset_label="test", operation_id=None)

    state = read_source_state(DatabaseManager(db_url).engine, "net-source")
    # rss_last_failed_at should be set and consecutive failures reset
    assert state.get("rss_last_failed_at") is not None
    assert state.get("rss_consecutive_failures", 0) == 0
