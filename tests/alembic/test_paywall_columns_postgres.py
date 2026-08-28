"""The paywall columns arrive on a table that already has rows in it.

`has_paywall` is NOT NULL. Adding a NOT NULL column to a populated table
fails outright unless it carries a server default, and a test that
migrates an empty database never finds out -- production has 1,149
publisher records and the test database would have none.

So this seeds a row first, then migrates, then reads it back.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL")
    or "postgresql" not in os.getenv("TEST_DATABASE_URL", ""),
    reason="PostgreSQL test database not configured",
)
def test_paywall_columns_land_on_a_table_that_has_rows():
    database_url = os.getenv("TEST_DATABASE_URL")
    project_root = Path(__file__).parent.parent.parent
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["USE_CLOUD_SQL_CONNECTOR"] = "false"

    engine = create_engine(database_url)

    # One migration short of the one under test, so the row is written
    # before the columns exist -- which is the state production is in.
    down = subprocess.run(
        ["alembic", "downgrade", "d86ffabfebe9"],
        capture_output=True,
        text=True,
        env=env,
        cwd=project_root,
    )
    assert down.returncode == 0, down.stderr

    host = f"paywalltest-{uuid.uuid4().hex[:8]}.example"
    source_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sources (id, host, host_norm) "
                "VALUES (:id, :host, :host)"
            ),
            {"id": source_id, "host": host},
        )

    up = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        cwd=project_root,
    )
    assert up.returncode == 0, up.stderr

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT has_paywall, subscription_cost, subscription_period, "
                "login_url FROM sources WHERE id = :id"
            ),
            {"id": source_id},
        ).one()
        # The record that was already there: not paywalled rather than
        # null, because an unticked box is an answer and a null is not.
        assert row.has_paywall is False
        assert row.subscription_cost is None
        assert row.subscription_period is None
        assert row.login_url is None

        # And the columns take what they are for.
        conn.execute(
            text(
                "UPDATE sources SET has_paywall = TRUE, "
                "subscription_cost = 12.99, subscription_period = 'monthly', "
                "login_url = :url WHERE id = :id"
            ),
            {"id": source_id, "url": f"https://{host}/login"},
        )
        back = conn.execute(
            text(
                "SELECT has_paywall, subscription_cost, subscription_period "
                "FROM sources WHERE id = :id"
            ),
            {"id": source_id},
        ).one()
        assert back.has_paywall is True
        # Numeric, not float: money in a float is money that does not add up.
        assert str(back.subscription_cost) == "12.99"
        assert back.subscription_period == "monthly"

        conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})
