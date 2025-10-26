import uuid
from collections import defaultdict
from datetime import datetime

import pytest
from sqlalchemy import text

from src.cli.commands import extraction
from src.models.database import DatabaseManager


class FakeExtractor:
    def __init__(self, raise_on_extract=True):
        self.raise_on_extract = raise_on_extract

    def extract_content(self, url, metrics=None):
        # Simulate an extraction that fails with HTTP 403; we set metrics
        # attributes so the telemetry logic will see them.
        if metrics is not None:
            metrics.http_status_code = 403
            # extract host from url naively for test; the real extractor
            # would set a host value on the metrics
            metrics.host = "example.com"

        if self.raise_on_extract:
            raise Exception("HTTP 403")
        return {}

    def _check_rate_limit(self, domain):
        return False


@pytest.fixture()
def db_manager(tmp_path):
    # Use an on-disk sqlite DB under tmp_path to allow SQLAlchemy to open
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    dm = DatabaseManager(database_url=db_url)

    # Create minimal candidate_links and articles tables required by the
    # _process_batch function and by the test.
    with dm.engine.begin() as conn:
        # Check if tables exist first
        res = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='candidate_links'"
            )
        )
        if not res.fetchone():
            conn.execute(
                text(
                    """
                    CREATE TABLE candidate_links (
                        id TEXT PRIMARY KEY,
                        url TEXT,
                        source TEXT,
                        source_id TEXT,
                        status TEXT,
                        error_message TEXT,
                        created_at TEXT,
                        discovered_at TEXT
                    )
                    """
                )
            )

        res = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='articles'"
            )
        )
        if not res.fetchone():
            conn.execute(
                text(
                    """
                    CREATE TABLE articles (
                        id TEXT PRIMARY KEY,
                        candidate_link_id TEXT
                    )
                    """
                )
            )

    return dm


def insert_candidate(conn, id_, url, source, status="article"):
    conn.execute(
        text(
            "INSERT INTO candidate_links "
            "(id, url, source, status, created_at, discovered_at)"
            " VALUES "
            "(:id, :url, :source, :status, :created_at, :discovered_at)"
        ),
        {
            "id": id_,
            "url": url,
            "source": source,
            "status": status,
            "created_at": datetime.now().isoformat(),
            "discovered_at": datetime.now().isoformat(),
        },
    )


def test_pause_on_two_403s(db_manager):
    dm = db_manager
    # Insert two example.com candidate links to trigger host pause
    with dm.engine.begin() as conn:
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        insert_candidate(conn, id1, "https://example.com/a", "example.com")
        insert_candidate(conn, id2, "https://example.com/b", "example.com")

    # Prepare args object with minimal attributes used by _process_batch
    class Args:
        source = None
        limit = 10
        continue_on_error = True
        skip_telemetry = True
        db_url = db_manager.database_url
        batch_size = 10

    args = Args()

    # Create fake extractor that sets metrics to 403 and raises
    fake_extractor = FakeExtractor()
    fake_byline = None
    fake_telemetry = type("T", (), {"record_extraction": lambda *a, **k: None})()

    # Call _process_batch twice, first will record one 403, second will hit
    # threshold and pause candidate links.
    # Note: _process_batch expects a DatabaseManager session via
    # DatabaseManager(). We call it with our DatabaseManager to ensure
    # it connects to the test DB.

    # First run
    host_403_tracker = {}
    domains_for_cleaning = defaultdict(list)
    extraction._process_batch(
        args,
        fake_extractor,
        fake_byline,
        fake_telemetry,
        per_batch=10,
        batch_num=1,
        host_403_tracker=host_403_tracker,
        domains_for_cleaning=domains_for_cleaning,
    )

    # Second run: this should trigger the pause update
    extraction._process_batch(
        args,
        fake_extractor,
        fake_byline,
        fake_telemetry,
        per_batch=10,
        batch_num=2,
        host_403_tracker=host_403_tracker,
        domains_for_cleaning=domains_for_cleaning,
    )

    # Print the tracker to see what's in it
    print(f"Host 403 tracker: {host_403_tracker}")

    # Monkey-patch the extraction module to use our database
    original_db_init = extraction.DatabaseManager.__init__

    def patched_init(self, database_url=None):
        if database_url is None:
            database_url = db_manager.database_url
        return original_db_init(self, database_url)

    extraction.DatabaseManager.__init__ = patched_init

    # Run one more time to properly use our test database with the patch
    extraction._process_batch(
        args,
        fake_extractor,
        fake_byline,
        fake_telemetry,
        per_batch=10,
        batch_num=3,
        host_403_tracker=host_403_tracker,
        domains_for_cleaning=domains_for_cleaning,
    )

    # Now verify candidate_links rows are paused
    with dm.engine.begin() as conn:
        res = conn.execute(
            text("SELECT id, status, error_message, url FROM candidate_links")
        )
        rows = list(res)
        assert len(rows) == 2
        for r in rows:
            assert r[1] == "paused"  # status is the second column (index 1)
            # error_message is the third column (index 2)
            assert r[2] == "Auto-paused: multiple HTTP 403 responses"
