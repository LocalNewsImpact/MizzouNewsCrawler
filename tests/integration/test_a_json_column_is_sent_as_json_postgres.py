"""The same insert against a real PostgreSQL json column."""

from __future__ import annotations

import os
import uuid

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from src.models.database import bulk_insert_candidate_links

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL")
    or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
    reason="PostgreSQL test database not configured",
)
def test_a_row_with_meta_lands_and_reads_back_as_json():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    url = f"https://json-probe-{uuid.uuid4().hex[:8]}.example/story"
    df = pd.DataFrame(
        [
            {
                "url": url,
                "source": "probe",
                "status": "discovered",
                "discovered_by": "test",
                "meta": '{"manual_import": true}',
            }
        ]
    )
    try:
        assert bulk_insert_candidate_links(engine, df, if_exists="append") == 1
        with engine.begin() as conn:
            meta = conn.execute(
                text("SELECT meta FROM candidate_links WHERE url = :u"), {"u": url}
            ).scalar()
        assert (meta if isinstance(meta, dict) else __import__("json").loads(meta)) == {
            "manual_import": True
        }
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM candidate_links WHERE url = :u"), {"u": url})
