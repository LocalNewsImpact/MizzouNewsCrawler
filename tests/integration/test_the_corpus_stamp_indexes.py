"""The corpus stamp's four maxima are each read off the end of an index.

Datadesk re-derives `corpus_version` every five minutes, and four of its
parts are `max()` over a column with no btree of its own. `687d44c97977`
adds one per column. What matters is not that four indexes exist but
that the planner answers each max from one -- in particular the two
`articles` maxima, which datadesk asks in ONE aggregate, and which
Postgres answers with one index read each only when both columns have
their own index.

Run against a stub `op`, for the reason `test_the_blocked_page_indexes`
gives: `tests/alembic` shadows the installed library once it is imported.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "687d44c97977_the_corpus_stamp_reads_four_indexes.py"
)

#: What datadesk's `_stamp_now` sends, one statement per table.
STAMP_QUERIES = {
    "articles": (
        "SELECT max(created_at), max(entities_extracted_at) FROM articles",
        ("ix_articles_created_at", "ix_articles_entities_extracted_at"),
    ),
    "article_enrichment": (
        "SELECT max(enriched_at) FROM article_enrichment",
        ("ix_article_enrichment_enriched_at",),
    ),
    "article_places_manual": (
        "SELECT max(added_at) FROM article_places_manual",
        ("ix_article_places_manual_added_at",),
    ),
}


class _RecordingOp:
    """The one member of `op` this migration uses. Every statement runs."""

    def __init__(self, conn):
        self._conn = conn
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        self._conn.execute(text(sql))


def _load(stub):
    """Import the migration with `alembic.op` bound to the stub.

    The migration binds `op` at import time, so the stub has to be in
    place while it is imported; whatever `alembic` was is put back.
    """
    fake = types.ModuleType("alembic")
    fake.op = stub
    shadowed = {
        name: module
        for name, module in sys.modules.items()
        if name == "alembic" or name.startswith("alembic.")
    }
    for name in shadowed:
        del sys.modules[name]
    sys.modules["alembic"] = fake
    try:
        spec = importlib.util.spec_from_file_location("stamp_idx", MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        del sys.modules["alembic"]
        sys.modules.update(shadowed)
    return module


@pytest.fixture
def migrated():
    if not HAS_POSTGRES:
        pytest.skip("TEST_DATABASE_URL is not Postgres")
    engine = create_engine(POSTGRES_TEST_URL)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS articles (id uuid PRIMARY KEY, "
                "created_at timestamp, entities_extracted_at timestamp)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS article_enrichment "
                "(article_id uuid PRIMARY KEY, enriched_at timestamptz)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS article_places_manual "
                "(id serial PRIMARY KEY, added_at timestamptz)"
            )
        )
        stub = _RecordingOp(conn)
        module = _load(stub)
        for name, _table, _column in module.INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        conn.commit()
        module.upgrade()
        conn.commit()
        conn.stub = stub
        conn.module = module
        yield conn
        conn.rollback()


def _definition(conn, name):
    return conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": name}
    ).scalar()


def _plan(conn, sql):
    return "\n".join(str(row[0]) for row in conn.execute(text("EXPLAIN " + sql)))


def test_each_column_has_its_own_whole_index(migrated):
    """One column, every row. A partial index -- like the pending-entities
    one already on `articles` -- cannot answer a max over the whole table."""
    for name, table, column in migrated.module.INDEXES:
        definition = _definition(migrated, name)
        assert definition is not None, f"{name} was not created"
        assert f"ON public.{table} USING btree ({column})" in definition
        assert "WHERE" not in definition, f"{name} is partial: {definition}"


@pytest.mark.parametrize("table", sorted(STAMP_QUERIES))
def test_the_planner_reads_each_max_from_its_index(migrated, table):
    """The point of the indexes, asked of the planner.

    Sequential scans are disabled because the test tables are empty, and a
    scan of nothing is genuinely cheaper; what is under test is whether
    each max CAN be read from an index, which with no index it cannot.
    For `articles` both maxima come from one statement, and each has to
    be served by its own index for the scan to go away.
    """
    sql, expected = STAMP_QUERIES[table]
    migrated.execute(text("SET enable_seqscan = off"))
    plan = _plan(migrated, sql)
    for name in expected:
        assert name in plan, f"{name} does not serve {sql}:\n{plan}"
    assert "Seq Scan" not in plan, f"{sql} still scans:\n{plan}"


def test_running_it_twice_is_harmless(migrated):
    """Production carries these first, built CONCURRENTLY by hand; the
    migration has to be a no-op there, not a failure."""
    for statement in list(migrated.stub.statements):
        migrated.execute(text(statement))
    migrated.commit()
    for name, _table, _column in migrated.module.INDEXES:
        assert _definition(migrated, name) is not None


def test_downgrade_removes_exactly_these(migrated):
    migrated.module.downgrade()
    migrated.commit()
    for name, _table, _column in migrated.module.INDEXES:
        assert _definition(migrated, name) is None, f"{name} survived downgrade"
    # Put them back for whatever runs next against the shared database.
    migrated.module.upgrade()
    migrated.commit()
