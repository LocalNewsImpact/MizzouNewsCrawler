import json
import pathlib
import sys

import pandas as pd
import pytest

# Ensure the project root is on sys.path so `src` imports resolve when
# running tests directly.
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.crawler.discovery import NewsDiscovery  # noqa: E402
from src.models.database import (  # noqa: E402
    DatabaseManager,
    read_candidate_links,
)
from src.utils.discovery_outcomes import DiscoveryOutcome  # noqa: E402


def _dummy_feed_return(source_url: str):
    return [
        {
            "url": "https://example.com/old-article",
            "source_url": source_url,
            "discovery_method": "rss_feed",
            "discovered_at": "2025-09-20T00:00:00",
            "title": "Old Article",
            "metadata": {
                "rss_feed_url": "https://example.com/feed",
                "feed_entry_count": 3,
                "fallback_include_older": True,
            },
        }
    ]


@pytest.fixture
def tmp_db_path(tmp_path):
    db_file = tmp_path / "test_mizzou.db"
    return f"sqlite:///{db_file}"


def test_fallback_flag_persisted(tmp_db_path, monkeypatch):
    # Prepare a minimal source row as pandas Series
    src = pd.Series(
        {
            "id": "dummy-source-id",
            "name": "Dummy Source",
            "url": "https://example.com",
            "metadata": json.dumps({"frequency": "monthly"}),
        }
    )

    # Create a normal NewsDiscovery instance and monkeypatch the
    # discover_with_rss_feeds method to return our fallback result.
    discovery = NewsDiscovery(database_url=tmp_db_path)

    def dummy_rss_success(*args, **kwargs):
        return (
            _dummy_feed_return(args[0]),
            {
                "feeds_tried": 1,
                "feeds_successful": 1,
                "network_errors": 0,
            },
        )

    # Monkeypatch the instance method
    discovery.discover_with_rss_feeds = dummy_rss_success

    # Monkeypatch DatabaseManager to ensure isolated DB engine
    dbm = DatabaseManager(database_url=tmp_db_path)

    # Ensure tables created
    dbm.close()

    # Run process_source which should call our dummy RSS discovery
    result = discovery.process_source(
        src, dataset_label="test", operation_id=None
    )
    assert result.articles_new == 1
    assert result.metadata.get("stored_count") == 1
    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND

    # Verify row in DB contains the fallback flag in meta
    dm = DatabaseManager(database_url=tmp_db_path)
    df = read_candidate_links(dm.engine)
    # Debugging helper if test fails
    if len(df) == 0:
        pytest.fail(
            "No rows inserted into candidate_links; check process_source path"
        )
    assert len(df) == 1
    meta = df["meta"].iloc[0]
    # meta may be loaded as dict or JSON string depending on driver
    if isinstance(meta, str):
        meta_obj = json.loads(meta)
    else:
        meta_obj = meta
    assert meta_obj.get("fallback_include_older") is True
    dm.close()
