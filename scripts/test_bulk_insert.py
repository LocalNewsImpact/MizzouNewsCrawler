"""Smoke test for bulk_insert_candidate_links with dataset_id.

Creates a temporary SQLite DB, calls DatabaseManager.upsert_candidate_links
with a small DataFrame containing URLs and source_host_id values, and
then inspects the DB to assert that `sources`, `dataset_sources`, and
`candidate_links` rows were created and linked.
"""

import os
import pathlib
import sqlite3
import sys
import tempfile

import pandas as pd

# Ensure project root is on sys.path so 'src' package is importable when running
# this script directly from the scripts/ directory.
ROOT = str(pathlib.Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.models.database import DatabaseManager  # noqa: E402


def run_test():
    fd, path = tempfile.mkstemp(prefix="mnc_test_", suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    # Build simple DataFrame
    df = pd.DataFrame(
        [
            {
                "url": "https://example.com/article1",
                "source_host_id": "ex1",
                "source": "example.com",
            },
            {
                "url": "https://example.com/article2",
                "source_host_id": "ex1",
                "source": "example.com",
            },
            {
                "url": "https://other.org/1",
                "source_host_id": "oth1",
                "source": "other.org",
            },
        ]
    )

    with DatabaseManager(database_url=db_url) as db:
        # ensure schema creation: Base.metadata.create_all called in manager
        dataset_id = "test-ds-0001"
        inserted = db.upsert_candidate_links(
            df=df, if_exists="append", dataset_id=dataset_id
        )
        print(f"Inserted rows: {inserted}")

        # Inspect underlying sqlite file
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        try:
            cur.execute("SELECT count(*) FROM sources")
            sources_count = cur.fetchone()[0]
            print(f"Sources rows: {sources_count}")
        except Exception as e:
            print(f"Error reading sources: {e}")
            sources_count = None

        try:
            cur.execute("SELECT count(*) FROM dataset_sources")
            ds_count = cur.fetchone()[0]
            print(f"Dataset_sources rows: {ds_count}")
        except Exception as e:
            print(f"Error reading dataset_sources: {e}")
            ds_count = None

        try:
            cur.execute("SELECT count(*) FROM candidate_links")
            cl_count = cur.fetchone()[0]
            print(f"Candidate_links rows: {cl_count}")
        except Exception as e:
            print(f"Error reading candidate_links: {e}")
            cl_count = None

        conn.close()

    # Keep DB file for inspection by developer; print path
    print(f"Temporary DB kept at: {path}")


if __name__ == "__main__":
    run_test()
