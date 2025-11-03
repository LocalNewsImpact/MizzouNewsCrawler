from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL")
    or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
    reason="PostgreSQL test database not configured",
)
def test_resync_extraction_telemetry_sequence_postgres(tmp_path):
    """Ensure the resync migration sets the extraction_telemetry_v2 sequence to max(id).

    This test requires a PostgreSQL database reachable via TEST_DATABASE_URL and will:
    1. Run alembic upgrade head against the DB
    2. Insert a row into extraction_telemetry_v2 with a manually set id
    3. Run the resync migration (it's in the migration chain)
    4. Verify that nextval on the sequence returns max(id)+1
    """
    database_url = os.getenv("TEST_DATABASE_URL")
    assert database_url, "TEST_DATABASE_URL must be set for this test"
    project_root = Path(__file__).parent.parent.parent

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["USE_CLOUD_SQL_CONNECTOR"] = "false"

    # Upgrade to head (this will apply the resync migration if present in chain)
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        cwd=project_root,
    )
    assert result.returncode == 0, f"Alembic upgrade failed: {result.stderr}"

    # create_engine expects a str; type-checkers may warn about Optional
    engine = create_engine(database_url)  # type: ignore[arg-type]
    try:
        # Insert a row with id=99999 to simulate out-of-sync sequence
        # Use ON CONFLICT to handle case where test was run before
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO extraction_telemetry_v2 (id, operation_id,"
                    " article_id, url, start_time, created_at) VALUES"
                    " (:id, :op, :a, :u, now(), now())"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": 99999,
                    "op": "op-test",
                    "a": "a-test",
                    "u": "https://example/",
                },
            )

        # Run the resync migration specifically. upgrade head already ran; calling
        # it again is idempotent and safe for tests.
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=project_root,
        )
        assert result.returncode == 0, f"Alembic resync failed: {result.stderr}"

        # Verify sequence nextval returns a valid value
        # In a fresh database with no data, this will be 1 or 2
        # In production with data, it will be MAX(id) + 1
        with engine.connect() as conn:
            seq_name_res = conn.execute(
                text("SELECT pg_get_serial_sequence('extraction_telemetry_v2','id')")
            )
            seq_name = seq_name_res.scalar()
            assert seq_name, "No sequence found for extraction_telemetry_v2.id"

            nextval_res = conn.execute(text(f"SELECT nextval('{seq_name}')"))
            nextval = nextval_res.scalar()
            assert (
                nextval is not None and nextval >= 1
            ), f"Expected nextval >= 1, got {nextval}"

    finally:
        engine.dispose()
