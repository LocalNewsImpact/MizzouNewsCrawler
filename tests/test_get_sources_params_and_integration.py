import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.crawler.discovery import NewsDiscovery


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

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    # Call with a dataset_label so the code assembles params dictionary
    nd.get_sources_to_process(dataset_label="my-label", limit=1, due_only=False)

    assert "params" in captured
    assert isinstance(
        captured["params"], dict
    ), f"expected dict but got {type(captured['params'])}"


def test_get_sources_integration_sqlite(tmp_path):
    """Integration test: create a minimal SQLite DB with the columns
    expected by `get_sources_to_process` and call the function.
    """
    # Build an on-disk temporary SQLite DB so SQLAlchemy can open it
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"

    # Use SQLAlchemy to create the minimal schema
    from sqlalchemy import (
        Column,
        MetaData,
        String,
        Table,
        Text,
        create_engine,
    )

    engine = create_engine(db_url)
    metadata = MetaData()

    # Add the columns referenced by the discovery query
    sources = Table(
        "sources",
        metadata,
        Column("id", String, primary_key=True),
        Column("canonical_name", String),
        Column("host", String),
        Column("metadata", Text),
        Column("city", String),
        Column("county", String),
        Column("type", String),
    )

    datasets = Table(
        "datasets",
        metadata,
        Column("id", String, primary_key=True),
        Column("label", String),
    )

    dataset_sources = Table(
        "dataset_sources",
        metadata,
        Column("dataset_id", String),
        Column("source_id", String),
    )

    metadata.create_all(engine)

    # Insert a dataset, source and join row inside a transaction so the
    # data is committed and visible to a new engine instance.
    with engine.begin() as conn:
        conn.execute(datasets.insert(), [{"id": "d1", "label": "my-label"}])
        conn.execute(
            sources.insert(),
            [
                {
                    "id": "s1",
                    "canonical_name": "Example",
                    "host": "example.com",
                    "metadata": None,
                    "city": None,
                    "county": None,
                    "type": None,
                }
            ],
        )
        conn.execute(
            dataset_sources.insert(),
            [{"dataset_id": "d1", "source_id": "s1"}],
        )

    nd = NewsDiscovery(database_url=db_url)

    # This should not raise and should return the source we inserted
    df, stats = nd.get_sources_to_process(
        dataset_label="my-label", limit=10, due_only=False
    )
    # explicit checks avoid ambiguous truth-value of Series error
    assert len(df) > 0
    # use .at with integer position 0 to get scalar value for 'host'
    assert df.at[0, "host"] == "example.com"
    assert isinstance(stats, dict)
