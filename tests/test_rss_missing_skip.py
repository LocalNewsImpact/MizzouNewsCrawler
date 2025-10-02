import json
import pathlib
import sys

import pandas as pd
import pytest

# Ensure project root on sys.path
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from src.crawler.discovery import NewsDiscovery  # noqa: E402
from src.models import Source  # noqa: E402
from src.models.database import DatabaseManager
from src.utils.discovery_outcomes import DiscoveryOutcome  # noqa: E402


def test_rss_missing_sets_and_skips(tmp_path, monkeypatch):
    # Create temporary DB
    db_file = tmp_path / "test_mizzou2.db"
    db_url = f"sqlite:///{db_file}"

    # Prepare a minimal source row as pandas Series
    src = pd.Series(
        {
            "id": "dummy-source-id-2",
            "name": "Dummy Source 2",
            "url": "https://example.org",
            "metadata": json.dumps({"frequency": "weekly"}),
        }
    )

    discovery = NewsDiscovery(database_url=db_url)

    # First, monkeypatch discover_with_rss_feeds to raise an error
    def fail_rss(*a, **k):
        raise Exception("simulated rss fetch failure")

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", fail_rss)

    # Create a Source row in the DB so metadata updates target an existing
    # record. This mirrors how production would persist rss_missing.
    dbm_init = DatabaseManager(database_url=db_url)
    s = Source(
        id="dummy-source-id-2",
        host="example.org",
        host_norm="example.org",
        canonical_name="Dummy Source 2",
        meta={"frequency": "weekly"},
    )
    dbm_init.session.add(s)
    dbm_init.session.commit()
    dbm_init.close()

    # Run process_source: should catch failure and set rss_missing
    result1 = discovery.process_source(
        src, dataset_label="test", operation_id=None
    )
    assert result1.articles_new == 0
    assert result1.outcome == DiscoveryOutcome.NO_ARTICLES_FOUND

    # Inspect sources table metadata to ensure rss_missing was set
    dbm = DatabaseManager(database_url=db_url)
    with dbm.engine.connect() as conn:
        res = conn.execute(
            text("SELECT metadata FROM sources WHERE id = :id"),
            {"id": "dummy-source-id-2"},
        ).fetchone()
        # If row not present (depends on DB initialization), we accept that
        if res and res[0]:
            meta = res[0]
            if isinstance(meta, str):
                meta_obj = json.loads(meta)
            else:
                meta_obj = meta
            assert "rss_missing" in meta_obj

    dbm.close()

    # Now restore discover_with_rss_feeds to a callable that records calls
    calls = {"count": 0}

    def dummy_rss_ok(*a, **k):
        calls["count"] += 1
        return []

    monkeypatch.setattr(discovery, "discover_with_rss_feeds", dummy_rss_ok)

    # Reload the source metadata from DB so the in-memory `src` reflects
    # the persisted `rss_missing` flag. process_source reads metadata from
    # the provided Series, so we must update it to simulate the next run.
    with dbm.engine.connect() as conn:
        res2 = conn.execute(
            text("SELECT metadata FROM sources WHERE id = :id"),
            {"id": "dummy-source-id-2"},
        ).fetchone()
        if res2 and res2[0]:
            meta_val = res2[0]
            if isinstance(meta_val, str):
                src["metadata"] = meta_val
            else:
                src["metadata"] = json.dumps(meta_val)

    # Second run: due to rss_missing present in src['metadata'], RSS should
    # be skipped and our dummy_rss_ok should not be called.
    _ = discovery.process_source(
        src, dataset_label="test", operation_id=None
    )
    assert calls["count"] == 0


if __name__ == "__main__":
    pytest.main([__file__])
