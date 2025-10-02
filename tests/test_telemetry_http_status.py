import pathlib
import sys

# Ensure project root
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from src.models.database import DatabaseManager  # noqa: E402
from src.utils.telemetry import (  # noqa: E402
    DiscoveryMethod,
    OperationTracker,
)


def test_track_http_status_inserts_row(tmp_path):
    db_file = tmp_path / "telemetry_test.db"
    db_url = f"sqlite:///{db_file}"

    dbm = DatabaseManager(database_url=db_url)
    # Create an OperationTracker using the engine
    tracker = OperationTracker(dbm.engine)

    # Call track_http_status
    tracker.track_http_status(
        operation_id="op-1",
        source_id="src-1",
        source_url="https://example.org",
        discovery_method=DiscoveryMethod.RSS_FEED,
        attempted_url="https://example.org/rss",
        status_code=404,
        response_time_ms=123.4,
        error_message="Not found",
        content_length=0,
    )

    # Verify row exists and fields are stored correctly
    with dbm.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT source_id, discovery_method, status_code, "
                "status_category, response_time_ms, attempted_url, "
                "error_message, content_length, operation_id "
                "FROM http_status_tracking WHERE source_id = :sid LIMIT 1"
            ),
            {"sid": "src-1"},
        ).fetchone()

        assert row is not None
        assert row.source_id == "src-1"
        # discovery_method stored as the value string of the enum
        assert row.discovery_method == DiscoveryMethod.RSS_FEED.value
        assert row.status_code == 404
        assert row.status_category == "4xx"
        # response_time_ms stored as float (approximately)
        assert abs(row.response_time_ms - 123.4) < 0.001
        assert row.attempted_url == "https://example.org/rss"
        assert row.error_message == "Not found"
        assert row.content_length == 0
        assert row.operation_id == "op-1"

    dbm.close()
