import json
import pathlib
import sys
from datetime import datetime, timedelta

import pandas as pd
import pytest

# Ensure project root on sys.path
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from src.crawler.discovery import NewsDiscovery  # noqa: E402
from src.models import Source  # noqa: E402
from src.models.database import DatabaseManager  # noqa: E402
from src.utils.discovery_outcomes import DiscoveryOutcome  # noqa: E402


def test_last_successful_and_rss_missing_expiry(tmp_path, monkeypatch):
    db_file = tmp_path / "test_mizzou3.db"
    db_url = f"sqlite:///{db_file}"

    # Prepare source series
    src = pd.Series(
        {
            "id": "dummy-src-3",
            "name": "Dummy Src 3",
            "url": "https://example.net",
            "metadata": json.dumps({"frequency": "weekly"}),
        }
    )

    discovery = NewsDiscovery(database_url=db_url)

    # Insert Source row
    dbm = DatabaseManager(database_url=db_url)
    s = Source(
        id="dummy-src-3",
        host="example.net",
        host_norm="example.net",
        canonical_name="Dummy Src 3",
        meta={"frequency": "weekly"},
    )
    dbm.session.add(s)
    dbm.session.commit()
    dbm.close()

    # 1) Simulate successful RSS discovery that returns one article
    def rss_success(*a, **k):
        return (
            [
                {
                    "url": "https://example.net/article-1",
                    "discovery_method": "rss_feed",
                    "discovered_at": datetime.utcnow().isoformat(),
                    "metadata": {
                        "rss_feed_url": "https://example.net/feed"
                    },
                }
            ],
            {
                "feeds_tried": 1,
                "feeds_successful": 1,
                "network_errors": 0,
            },
        )

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", rss_success)

    # Run process_source and expect one stored candidate
    result = discovery.process_source(
        src, dataset_label="test", operation_id=None
    )
    assert result.articles_new == 1
    assert result.metadata.get("stored_count") == 1
    assert result.outcome == DiscoveryOutcome.NEW_ARTICLES_FOUND

    # Verify last_successful_method recorded and rss_missing cleared
    dbm2 = DatabaseManager(database_url=db_url)
    with dbm2.engine.connect() as conn:
        res = conn.execute(
            text("SELECT metadata FROM sources WHERE id = :id"),
            {"id": "dummy-src-3"},
        ).fetchone()
        assert res and res[0]
        meta = res[0]
        if isinstance(meta, str):
            mobj = json.loads(meta)
        else:
            mobj = meta
        assert mobj.get("last_successful_method") == "rss_feed"
        # rss_missing should be absent or None
        assert (
            mobj.get("rss_missing") in (None, "")
            or "rss_missing" not in mobj
        )

    dbm2.close()

    # 2) Simulate old rss_missing in the past (older than window), and verify
    # that discovery runs again (i.e., not skipped).
    old_ts = (datetime.utcnow() - timedelta(days=100)).isoformat()
    dbm3 = DatabaseManager(database_url=db_url)
    dbm3.update_source_metadata("dummy-src-3", {"rss_missing": old_ts})
    dbm3.close()

    calls = {"count": 0}

    def rss_called(*a, **k):
        calls["count"] += 1
        return (
            [],
            {
                "feeds_tried": 1,
                "feeds_successful": 0,
                "network_errors": 0,
            },
        )

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", rss_called)

    # Reload metadata into src so process_source will see rss_missing
    dbm4 = DatabaseManager(database_url=db_url)
    with dbm4.engine.connect() as conn:
        res2 = conn.execute(
            text("SELECT metadata FROM sources WHERE id = :id"),
            {"id": "dummy-src-3"},
        ).fetchone()
        if res2 and res2[0]:
            mv = res2[0]
            if isinstance(mv, str):
                src["metadata"] = mv
            else:
                src["metadata"] = json.dumps(mv)
    dbm4.close()

    # Now run process_source; because rss_missing is old (100 days), the
    # window for weekly (3*7=21 days) should allow RSS to run and increment
    # our call counter.
    _ = discovery.process_source(src, dataset_label="test", operation_id=None)
    assert calls["count"] == 1
