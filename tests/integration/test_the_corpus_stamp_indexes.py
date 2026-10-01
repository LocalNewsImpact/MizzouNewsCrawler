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
The connection is in autocommit, which is what Alembic's
`autocommit_block` hands the migration, so CONCURRENTLY runs for real.
"""

import contextlib
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

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
    """The members of `op` this migration uses. Every statement runs."""

    def __init__(self, conn):
        self._conn = conn
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        self._conn.execute(text(sql))

    def get_bind(self):
        return self._conn

    def get_context(self):
        # The connection is already in autocommit; the block is the
        # migration's statement that it needs one.
        return types.SimpleNamespace(autocommit_block=contextlib.nullcontext)


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
    engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
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


def test_it_builds_concurrently(migrated):
    """A merge runs this against production, where a plain CREATE INDEX
    would hold off every write to `articles` while it read the table."""
    creates = [s for s in migrated.stub.statements if s.startswith("CREATE INDEX")]
    assert len(creates) == 4
    assert all("CONCURRENTLY" in s for s in creates), creates


def test_an_invalid_index_is_built_again(migrated):
    """A CONCURRENTLY build that fails leaves an INVALID index, which IF
    NOT EXISTS alone would count as done and the planner never use."""
    name = "ix_articles_created_at"
    try:
        migrated.execute(
            text(
                "UPDATE pg_index SET indisvalid = false WHERE indexrelid = "
                "(SELECT oid FROM pg_class WHERE relname = :n)"
            ),
            {"n": name},
        )
    except ProgrammingError:
        pytest.skip("marking an index invalid needs a superuser")
    migrated.module.upgrade()
    valid = migrated.execute(
        text(
            "SELECT i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :n"
        ),
        {"n": name},
    ).scalar()
    assert valid is True
    assert f"DROP INDEX CONCURRENTLY IF EXISTS {name}" in migrated.stub.statements


def test_running_it_twice_is_harmless(migrated):
    """A retried deploy runs it again over indexes that already stand; it
    has to be a no-op there, not a failure."""
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


#: Runs the migration the way the deploy does: Alembic's own
#: `autocommit_block`, inside env.py's transaction, over pg8000. In a
#: child process, so the installed `alembic` is the one imported.
_THROUGH_ALEMBIC = """
import importlib.util, sys
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

url, path = sys.argv[1], sys.argv[2]
with create_engine(url).connect() as conn:
    context = MigrationContext.configure(conn)
    with Operations.context(context), context.begin_transaction():
        spec = importlib.util.spec_from_file_location("stamp_idx", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade()
"""


def test_it_runs_through_alembic_on_pg8000(migrated, tmp_path):
    """The stub above hands the migration a connection already in
    autocommit, which is not what production does. Production migrates
    over pg8000, where Alembic's `autocommit_block` leaves a transaction
    open and CONCURRENTLY fails inside it -- the deploy of 2026-09-30."""
    pytest.importorskip("pg8000")
    url = migrated.engine.url.set(drivername="postgresql+pg8000")
    for name, _table, _column in migrated.module.INDEXES:
        migrated.execute(text(f"DROP INDEX IF EXISTS {name}"))
    migrated.commit()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _THROUGH_ALEMBIC,
            url.render_as_string(hide_password=False),
            str(MIGRATION),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    for name, _table, _column in migrated.module.INDEXES:
        assert _definition(migrated, name) is not None, f"{name} was not created"
