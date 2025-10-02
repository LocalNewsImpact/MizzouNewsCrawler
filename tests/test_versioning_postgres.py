import os

import pytest

POSTGRES_DSN = os.environ.get("POSTGRES_TEST_DSN")


@pytest.mark.skipif(
    not POSTGRES_DSN, reason="Postgres DSN not provided in POSTGRES_TEST_DSN"
)
def test_export_snapshot_postgres(tmp_path):
    from src.models import create_database_engine
    from src.models.versioning import (
        create_dataset_version,
        create_versioning_tables,
        export_snapshot_for_version,
    )

    engine = create_database_engine(POSTGRES_DSN)

    # create versioning tables
    create_versioning_tables(database_url=POSTGRES_DSN)

    # create a simple table to export
    table_name = "test_articles"
    with engine.begin() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS test_articles (
                id SERIAL PRIMARY KEY,
                title TEXT
            )
            """
        )
        # clear and insert sample rows
        conn.execute("TRUNCATE TABLE test_articles")
        conn.execute(
            "INSERT INTO test_articles (title) VALUES ('a'), ('b'), ('c')")

    dv = create_dataset_version(
        "test", "v-postgres", database_url=POSTGRES_DSN)

    out = tmp_path / "snapshot.parquet"
    dv2 = export_snapshot_for_version(
        dv.id, table_name, str(out), database_url=POSTGRES_DSN
    )

    assert out.exists(), "Snapshot file was not created"
    assert dv2.status == "ready"
    assert dv2.snapshot_path == str(out)
    assert dv2.row_count == 3
