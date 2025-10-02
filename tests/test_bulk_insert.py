import os
import pathlib
import sqlite3
import sys
import tempfile

import pandas as pd

ROOT = str(pathlib.Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.models.database import DatabaseManager  # noqa: E402


def run_with_df(df: pd.DataFrame, dataset_id: str = "ds-test"):
    fd, path = tempfile.mkstemp(prefix="mnc_test_", suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    with DatabaseManager(database_url=db_url) as db:
        inserted = db.upsert_candidate_links(
            df, if_exists="append", dataset_id=dataset_id
        )
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    return conn, cur, inserted, path


def test_duplicate_legacy_ids_ignored():
    df = pd.DataFrame(
        [
            {"url": "https://a.com/1", "source_host_id": "legacy-1", "source": "a.com"},
            {"url": "https://a.com/2", "source_host_id": "legacy-1", "source": "a.com"},
        ]
    )
    conn, cur, inserted, path = run_with_df(df, dataset_id="ds-dupe")
    assert inserted == 2
    cur.execute("SELECT count(*) FROM dataset_sources WHERE dataset_id = 'ds-dupe'")
    count = cur.fetchone()[0]
    # Expect only one mapping for the duplicate legacy id
    assert count == 1
    conn.close()
    os.remove(path)


def test_missing_host_no_source_id():
    df = pd.DataFrame(
        [
            {"url": "not-a-url", "source": "unknown"},
        ]
    )
    conn, cur, inserted, path = run_with_df(df, dataset_id="ds-missing")
    assert inserted == 1
    cur.execute("SELECT source_id FROM candidate_links")
    sid = cur.fetchone()[0]
    assert sid is None
    conn.close()
    os.remove(path)


def test_multiple_distinct_hosts():
    df = pd.DataFrame(
        [
            {"url": "https://b.com/1", "source_host_id": "b", "source": "b.com"},
            {"url": "https://c.org/1", "source_host_id": "c", "source": "c.org"},
        ]
    )
    conn, cur, inserted, path = run_with_df(df, dataset_id="ds-multi")
    assert inserted == 2
    cur.execute("SELECT count(*) FROM sources")
    source_count = cur.fetchone()[0]
    assert source_count >= 2
    cur.execute("SELECT count(*) FROM dataset_sources WHERE dataset_id = 'ds-multi'")
    ds_count = cur.fetchone()[0]
    assert ds_count == 2
    conn.close()
    os.remove(path)
