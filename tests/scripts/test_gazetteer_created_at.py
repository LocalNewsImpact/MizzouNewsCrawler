import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_engine():
    # Shared in-memory DB for the test process
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


@pytest.fixture()
def sqlite_engine():
    engine = _make_engine()
    # Create all tables
    from src.models import create_tables

    create_tables(engine)
    yield engine


def test_created_at_present_in_postgres_bulk_insert_branch(sqlite_engine):
    """
    Forces the non-ORM ("postgres") branch in scripts.populate_gazetteer, which
    uses session.execute(insert(tbl), rows). Validates that each inserted row has
    created_at set to a non-NULL value to prevent NOT NULL violations.
    """
    # Seed minimal dataset/source rows
    from src.models import Dataset, DatasetSource, Source, create_tables

    create_tables(sqlite_engine)
    Session = sessionmaker(bind=sqlite_engine)
    session = Session()

    ds = Dataset(id="ds-1", slug="test-ds", label="Test Dataset")
    src = Source(
        id="src-1",
        host="example.com",
        host_norm="example.com",
        canonical_name="Example News",
        city="Columbia",
        meta={"state": "MO"},
    )
    ds_src = DatasetSource(
        dataset_id=ds.id, source_id=src.id, legacy_host_id="example.com"
    )
    session.add_all([ds, src, ds_src])
    session.commit()

    # Mock geocoding and overpass responses
    nominatim_response = [{"lat": "38.9517", "lon": "-92.3341"}]
    overpass_response = {
        "elements": [
            {
                "type": "node",
                "id": 12345,
                "lat": 38.9530,
                "lon": -92.3345,
                "tags": {"name": "Sample School"},
            }
        ]
    }

    mock_get = Mock()
    mock_get.status_code = 200
    mock_get.json.return_value = nominatim_response

    mock_post = Mock()
    mock_post.status_code = 200
    mock_post.json.return_value = overpass_response

    # Import the module under test
    import importlib

    popmod = importlib.import_module("scripts.populate_gazetteer")

    # Patch DatabaseManager used by scripts.populate_gazetteer to return our engine
    class FakeDBM:
        def __init__(self, database_url: str):
            self.engine = sqlite_engine

    # Force the code path to the non-sqlite branch by masquerading the dialect name
    original_name = sqlite_engine.dialect.name
    sqlite_engine.dialect.name = "postgresql"

    try:
        with (
            patch("requests.get", return_value=mock_get),
            patch("requests.post", return_value=mock_post),
            patch("src.models.database.DatabaseManager", FakeDBM),
        ):
            popmod.main(
                database_url=str(sqlite_engine.url),
                dataset_slug="test-ds",
                dry_run=False,
            )
    finally:
        # Restore dialect name to avoid side effects on other tests
        sqlite_engine.dialect.name = original_name

    # Verify at least one row inserted and created_at is not NULL
    rows = session.execute(
        text("SELECT created_at FROM gazetteer ORDER BY created_at DESC LIMIT 1")
    ).fetchall()
    assert rows, "Expected at least one gazetteer row to be inserted"
    (created_at_val,) = rows[0]
    assert (
        created_at_val is not None
    ), "created_at should be populated in bulk insert path"

    session.close()
