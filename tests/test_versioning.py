import os
import sys
import tempfile
import sqlite3
import pandas as pd
from pathlib import Path

# Ensure project root is on sys.path so `models` package imports succeed
# Insert `src` directory so we can import `models` as a top-level package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

try:
    from models.versioning import create_versioning_tables, create_dataset_version, export_snapshot_for_version
except Exception as e:
    import pytest

    pytest.skip(f"Skipping versioning test due to import error: {e}", allow_module_level=True)


def test_export_snapshot_chunked():
    # Create a temporary SQLite DB file
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db_url = f"sqlite:///{db_path}"

    # Create tables
    engine = create_versioning_tables(database_url=db_url)

    # Create a dummy candidate_links table and insert multiple rows
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE candidate_links (id TEXT PRIMARY KEY, url TEXT, source_name TEXT)")
    rows = [(f"id-{i}", f"http://example.com/{i}", f"source-{i%10}") for i in range(5000)]
    cur.executemany("INSERT INTO candidate_links (id, url, source_name) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()

    # Create a dataset version record
    dv = create_dataset_version('candidate_links', 'test-v1', database_url=db_url)

    # Export snapshot to a temp file
    out_dir = tempfile.mkdtemp()
    out_path = os.path.join(out_dir, f"candidate_links_{dv.id}.parquet")

    exported = export_snapshot_for_version(dv.id, 'candidate_links', out_path, database_url=db_url)
    assert os.path.exists(exported)

    # Read back parquet and verify row count
    df = pd.read_parquet(exported)
    assert len(df) == 5000
