import os
import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.crawler.discovery import NewsDiscovery

# Check if PostgreSQL is available for testing
POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL


def test_get_sources_passes_dict_to_read_sql(monkeypatch):
    """Unit test: ensure get_sources_to_process passes params dict to
    `pandas.read_sql_query`.
    """
    nd = NewsDiscovery(database_url="sqlite:///:memory:")
    captured = {}

    def fake_read_sql_query(query, engine, params=None):
        captured["params"] = params
        # return an empty dataframe matching expected columns
        cols = [
            "id",
            "name",
            "url",
            "metadata",
            "city",
            "county",
            "type_classification",
            "host",
        ]
        return pd.DataFrame([], columns=cols)

    # Mock dataset resolution to return a valid UUID
    def fake_resolve_dataset_id(engine, label):
        return "00000000-0000-0000-0000-000000000001"

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)
    monkeypatch.setattr(
        "src.utils.dataset_utils.resolve_dataset_id", fake_resolve_dataset_id
    )

    # Call with a dataset_label so the code assembles params dictionary
    nd.get_sources_to_process(dataset_label="my-label", limit=1, due_only=False)

    assert "params" in captured
    assert isinstance(
        captured["params"], dict
    ), f"expected dict but got {type(captured['params'])}"


@pytest.mark.postgres
@pytest.mark.integration
def test_get_sources_integration_postgres():
    """Integration test with PostgreSQL: full round-trip through get_sources_to_process.

    This test verifies dataset filtering works end-to-end with PostgreSQL,
    using the actual database schema created by Alembic migrations.
    """
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured (set TEST_DATABASE_URL)")

    from sqlalchemy import create_engine, text

    assert POSTGRES_TEST_URL is not None

    engine = create_engine(POSTGRES_TEST_URL)

    # Use test prefixes to avoid conflicts and enable cleanup
    test_dataset_id = "test-params-d1"
    test_source_id = "test-params-s1"

    try:
        # Insert test data using the actual PostgreSQL schema
        with engine.begin() as conn:
            # Clean up any existing test data first
            conn.execute(
                text("DELETE FROM dataset_sources WHERE dataset_id = :dataset_id"),
                {"dataset_id": test_dataset_id},
            )
            conn.execute(
                text("DELETE FROM sources WHERE id = :source_id"),
                {"source_id": test_source_id},
            )
            conn.execute(
                text("DELETE FROM datasets WHERE id = :dataset_id"),
                {"dataset_id": test_dataset_id},
            )

            # Insert dataset with ingested_at (required, no server default)
            conn.execute(
                text(
                    "INSERT INTO datasets (id, label, slug, ingested_at) "
                    "VALUES (:id, :label, :slug, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": test_dataset_id,
                    "label": "test-params-label",
                    "slug": "test-params-label",
                },
            )

            # Insert source (host_norm is required NOT NULL, no created_at)
            conn.execute(
                text(
                    "INSERT INTO sources (id, canonical_name, host, host_norm) "
                    "VALUES (:id, :name, :host, :host_norm)"
                ),
                {
                    "id": test_source_id,
                    "name": "Test Params Source",
                    "host": "test-params.example.com",
                    "host_norm": "test-params.example.com",
                },
            )

            # Link dataset and source (id column required)
            conn.execute(
                text(
                    "INSERT INTO dataset_sources (id, dataset_id, source_id) "
                    "VALUES (:id, :dataset_id, :source_id)"
                ),
                {
                    "id": f"{test_dataset_id}:{test_source_id}",
                    "dataset_id": test_dataset_id,
                    "source_id": test_source_id,
                },
            )

        nd = NewsDiscovery(database_url=POSTGRES_TEST_URL)

        # This should not raise and should return the source we inserted
        df, stats = nd.get_sources_to_process(
            dataset_label="test-params-label", limit=10, due_only=False
        )

        # explicit checks avoid ambiguous truth-value of Series error
        assert len(df) > 0, "Expected at least one source"
        # use .at with integer position 0 to get scalar value for 'host'
        assert df.at[0, "host"] == "test-params.example.com"
        assert isinstance(stats, dict)

    finally:
        # Clean up test data
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM dataset_sources WHERE dataset_id = :dataset_id"),
                {"dataset_id": test_dataset_id},
            )
            conn.execute(
                text("DELETE FROM sources WHERE id = :source_id"),
                {"source_id": test_source_id},
            )
            conn.execute(
                text("DELETE FROM datasets WHERE id = :dataset_id"),
                {"dataset_id": test_dataset_id},
            )
