import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Make sure repo root is importable (so `src.models` can be imported)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def create_in_memory_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


@pytest.fixture()
def in_memory_db():
    engine = create_in_memory_db()
    # Create all tables from ORM models to ensure the schema matches
    from src.models import create_tables

    create_tables(engine)
    yield engine


def test_populate_inserts_gazetteer_rows(in_memory_db):
    engine = in_memory_db
    # Create tables from ORM models so Dataset/Gazetteer schemas match
    from src.models import Dataset, DatasetSource, Source, create_tables

    create_tables(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Use ORM model instances so SQLAlchemy defaults are applied
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

    with patch("requests.get", return_value=mock_get), patch(
        "requests.post", return_value=mock_post
    ):
        import importlib

        popmod = importlib.import_module("scripts.populate_gazetteer")
        orig_create_engine = popmod.create_engine

        def _fake_create_engine(url):
            return engine

        popmod.create_engine = _fake_create_engine
        try:
            popmod.main(
                database_url=str(engine.url), dataset_slug="test-ds", dry_run=False
            )
        finally:
            popmod.create_engine = orig_create_engine

    res = session.execute(text("SELECT count(*) as c FROM gazetteer")).fetchone()
    assert res is not None
    assert res[0] >= 1

    row = session.execute(
        text(
            "SELECT dataset_id, dataset_label, source_id, data_id, "
            "host_id, name FROM gazetteer LIMIT 1"
        )
    ).fetchone()
    assert row is not None
    assert row[0] == "ds-1"
    assert row[1] == "Test Dataset"
    assert row[2] == "src-1"
    assert row[3] == "ds-1"
    assert row[4] == "example.com"
    assert "Sample School" in row[5]

    session.close()
