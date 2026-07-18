"""PostgreSQL integration tests for scripts/configure_publisher_auth.py.

The script's UPDATE uses ``CAST(:dataset_id AS TEXT)`` because PostgreSQL
cannot infer the type of a bare parameter that only appears in an ``IS NULL``
test — the pre-CAST statement raised ``could not determine data type of
parameter`` (42P18). The failure is driver-specific: pg8000 (used in
production via the Cloud SQL connector) sends server-side parameters and
trips the error, while psycopg2 interpolates client-side and never does. The
seeded fixture therefore points the script at the test database *via pg8000*
when it is installed, so these tests regression-protect the CAST fix for the
driver where it actually matters; SQLite-backed unit tests cannot.

Requires TEST_DATABASE_URL (the cloud_sql_engine fixture skips otherwise);
locally, `docker compose up -d postgres` provides one at
postgresql://mizzou_user:mizzou_pass@127.0.0.1:5432/mizzou.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.models import Base, Dataset, DatasetSource, Source

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "configure_publisher_auth.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "configure_publisher_auth", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def seeded(cloud_sql_engine, monkeypatch):
    """Seed two sources and a dataset containing only the first one.

    Points DATABASE_URL at the test database so the script's
    ``DatabaseManager()`` resolves to it deterministically — via the pg8000
    driver when available, because that is the driver on which the bare
    (un-CAST) ``:dataset_id`` parameter fails (42P18).
    """
    script_url = cloud_sql_engine.url
    try:
        import pg8000  # noqa: F401

        script_url = script_url.set(drivername="postgresql+pg8000")
    except ImportError:
        pass
    monkeypatch.setenv("DATABASE_URL", script_url.render_as_string(hide_password=False))

    Base.metadata.create_all(cloud_sql_engine, checkfirst=True)
    session = sessionmaker(bind=cloud_sql_engine)()

    suffix = uuid.uuid4().hex[:12]
    member = Source(
        host=f"www.member-{suffix}.example.test",
        host_norm=f"member-{suffix}.example.test",
        canonical_name="Member Paper",
    )
    outsider = Source(
        host=f"www.outsider-{suffix}.example.test",
        host_norm=f"outsider-{suffix}.example.test",
        canonical_name="Outsider Paper",
    )
    dataset = Dataset(
        slug=f"auth-test-{suffix}",
        label=f"Auth Test {suffix}",
        name=f"Auth Test {suffix}",
    )
    session.add_all([member, outsider, dataset])
    session.commit()
    session.add(DatasetSource(dataset_id=dataset.id, source_id=member.id))
    session.commit()

    yield {
        "session": session,
        "member": member,
        "outsider": outsider,
        "dataset": dataset,
    }

    session.execute(
        text("DELETE FROM dataset_sources WHERE dataset_id = :d"),
        {"d": dataset.id},
    )
    session.execute(text("DELETE FROM datasets WHERE id = :d"), {"d": dataset.id})
    session.execute(
        text("DELETE FROM sources WHERE id IN (:a, :b)"),
        {"a": member.id, "b": outsider.id},
    )
    session.commit()
    session.close()


def _auth_state(session, source_id):
    session.expire_all()
    row = session.execute(
        text(
            "SELECT requires_login, auth_type, auth_secret_name, auth_config"
            " FROM sources WHERE id = :id"
        ),
        {"id": source_id},
    ).fetchone()
    return {
        "requires_login": row[0],
        "auth_type": row[1],
        "auth_secret_name": row[2],
        "auth_config": row[3],
    }


def test_enable_without_dataset_regression_for_bare_null_param(seeded):
    """No --dataset -> :dataset_id is NULL in the IS NULL test.

    This is the exact statement shape that failed on PostgreSQL before the
    CAST(:dataset_id AS TEXT) fix ("could not determine data type of
    parameter $5"); SQLite accepts the bare parameter, so only a PostgreSQL
    run protects against regressing it.
    """
    script = _load_script()
    rc = script.main(
        [
            "--host",
            seeded["member"].host,
            "--auth-type",
            "simplecirc",
            "--secret-name",
            "publisher-auth-member-test",
            "--config",
            '{"login_url": "https://member.example.test/login/"}',
        ]
    )
    assert rc == 0

    state = _auth_state(seeded["session"], seeded["member"].id)
    assert state["requires_login"] is True
    assert state["auth_type"] == "simplecirc"
    assert state["auth_secret_name"] == "publisher-auth-member-test"
    config = state["auth_config"]
    if isinstance(config, str):
        config = json.loads(config)
    assert config == {"login_url": "https://member.example.test/login/"}


def test_dataset_scoping_updates_member_but_not_outsider(seeded):
    script = _load_script()

    rc = script.main(
        [
            "--host",
            seeded["member"].host,
            "--dataset",
            seeded["dataset"].slug,
            "--auth-type",
            "newzware",
            "--secret-name",
            "publisher-auth-member-test",
            "--config",
            '{"login_url": "https://member.example.test/login/"}',
        ]
    )
    assert rc == 0
    assert _auth_state(seeded["session"], seeded["member"].id)["auth_type"] == (
        "newzware"
    )

    # The outsider host exists but is not in the dataset: no row may update.
    rc = script.main(
        [
            "--host",
            seeded["outsider"].host,
            "--dataset",
            seeded["dataset"].slug,
            "--auth-type",
            "newzware",
            "--secret-name",
            "publisher-auth-outsider-test",
            "--config",
            "{}",
        ]
    )
    assert rc == 1
    state = _auth_state(seeded["session"], seeded["outsider"].id)
    assert state["requires_login"] in (False, None)
    assert state["auth_type"] is None


def test_disable_clears_auth_fields(seeded):
    script = _load_script()
    rc = script.main(
        [
            "--host",
            seeded["member"].host,
            "--auth-type",
            "form",
            "--secret-name",
            "publisher-auth-member-test",
            "--config",
            '{"login_url": "https://member.example.test/login/"}',
        ]
    )
    assert rc == 0

    rc = script.main(["--host", seeded["member"].host, "--disable"])
    assert rc == 0

    state = _auth_state(seeded["session"], seeded["member"].id)
    assert state["requires_login"] is False
    assert state["auth_type"] is None
    assert state["auth_secret_name"] is None
    assert state["auth_config"] is None
