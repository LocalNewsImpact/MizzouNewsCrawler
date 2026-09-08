"""An index whose predicate the planner cannot match is not an index.

The migration that adds these was written with `'%%k^Am%%'`, on the
assumption that Alembic hands the statement to a driver which reads a
lone percent as a placeholder and needs it escaped. It does not. The
doubled pattern was stored verbatim:

    WHERE (content ~~ '%%k^Am%%'::text)

which is still a *working* LIKE pattern -- two wildcards match what one
matches -- so nothing failed. It was built, it was maintained on every
write, and it was never used, because predicate implication is
structural and the Blocked page asks for `'%k^Am%'`. The page would have
gone on timing out with a green migration behind it.

Reading the SQL could not catch that. These run it and then ask Postgres
what it stored.

WHY THIS DOES NOT IMPORT ALEMBIC
--------------------------------
`tests/alembic/` is a package -- it has an `__init__.py` -- so once
pytest imports anything under it, `sys.modules["alembic"]` is that
directory and the installed library is shadowed for every test collected
afterwards. A first draft of this file did `from alembic.migration
import MigrationContext` and passed alone, in a worktree, and in the
venv the hook uses; it failed only in the full suite, where
`tests/alembic` is imported first:

    ModuleNotFoundError: No module named 'alembic.migration'

So the migration is executed against a stub carrying the two methods it
actually uses. What is under test is the SQL the migration sends and
what Postgres makes of it, neither of which is Alembic's to decide --
`op.execute` passes a string through to the connection, which is why the
doubled percent reached the database verbatim in the first place.
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
    / "u6v7w8x9y0z1_index_what_the_blocked_page_asks.py"
)

#: What the Blocked page asks, verbatim. The index has to serve this
#: exact predicate or it serves nothing.
ROT47_QUERY = "SELECT count(*) FROM articles WHERE content LIKE '%k^Am%'"

INDEXES = (
    "ix_articles_rot47_ciphertext",
    "ix_etv2_error_type",
    "ix_etv2_http_status_code",
)


class _RecordingOp:
    """The two members of `op` this migration uses, and nothing else.

    A stub rather than a mock: every statement really runs, and the
    statements are kept so a test can re-issue them.
    """

    def __init__(self, conn):
        self._conn = conn
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        self._conn.execute(text(sql))

    def get_bind(self):
        return self._conn


def _run_upgrade(conn):
    """Execute the migration's upgrade(), returning the SQL it sent.

    `alembic` is replaced in sys.modules for the duration, because the
    migration binds `op` at import time and the name may already point at
    tests/alembic. Whatever was there is put back.
    """
    stub = _RecordingOp(conn)
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
        spec = importlib.util.spec_from_file_location("blocked_idx", MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade()
    finally:
        del sys.modules["alembic"]
        sys.modules.update(shadowed)
    return stub.statements


@pytest.fixture
def migrated():
    if not HAS_POSTGRES:
        pytest.skip("TEST_DATABASE_URL is not Postgres")
    engine = create_engine(POSTGRES_TEST_URL)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS articles "
                "(id uuid PRIMARY KEY, content text)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS extraction_telemetry_v2 "
                "(id serial PRIMARY KEY, http_status_code int, "
                "error_type text, url text)"
            )
        )
        for name in INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        conn.commit()
        conn.statements = _run_upgrade(conn)
        conn.commit()
        yield conn


def _definition(conn, name):
    return conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": name}
    ).scalar()


def test_the_partial_predicate_is_not_double_escaped(migrated):
    """The percent signs reach Postgres as written."""
    definition = _definition(migrated, "ix_articles_rot47_ciphertext")
    assert definition is not None, "the partial index was not created"
    assert "'%k^Am%'" in definition, f"predicate was mangled: {definition}"
    assert "%%" not in definition, f"percent signs were doubled: {definition}"


def test_the_planner_will_use_the_partial_index(migrated):
    """The point of the index, asked of the planner rather than assumed.

    Sequential scan is disabled because the test table is small enough
    that a scan is genuinely cheaper; what is under test is whether the
    planner *can* match the predicate, not which it prefers on two rows.
    """
    migrated.execute(text("SET enable_seqscan = off"))
    plan = "\n".join(
        str(row[0]) for row in migrated.execute(text("EXPLAIN " + ROT47_QUERY))
    )
    assert "ix_articles_rot47_ciphertext" in plan, (
        "the planner cannot match the index predicate to the query:\n" + plan
    )


def test_the_shipped_pattern_matches_ciphertext_and_nothing_else(migrated):
    """A pattern wrong in the other direction -- too greedy -- would
    index every row and still read as a partial index.

    Asked of Postgres with literals rather than by inserting: `articles`
    requires a candidate_link_id, and building a link and a source to
    prove a LIKE pattern would test the fixtures. The pattern is lifted
    out of the statement the migration actually sent, so this checks what
    shipped and not a copy of it.
    """
    sent = [s for s in migrated.statements if "rot47" in s]
    assert sent, "the migration sent no ROT47 statement"
    pattern = sent[0].split("LIKE ")[1].strip()
    assert pattern == "'%k^Am%'", f"unexpected pattern: {pattern}"

    matches, misses = migrated.execute(
        text(f"SELECT 'body k^Am more' LIKE {pattern}, 'ordinary prose' LIKE {pattern}")
    ).fetchone()
    assert matches is True, "the pattern does not match ROT47 ciphertext"
    assert misses is False, "the pattern matches ordinary prose"


@pytest.mark.parametrize(
    "name,column",
    [
        ("ix_etv2_http_status_code", "http_status_code"),
        ("ix_etv2_error_type", "error_type"),
    ],
)
def test_the_fetch_failure_columns_are_indexed(migrated, name, column):
    """Five counts on this table read 838 MB each without these."""
    definition = _definition(migrated, name)
    assert definition is not None, f"{name} was not created"
    assert column in definition


def test_running_it_twice_is_harmless(migrated):
    """Production already carries these, built out of band with
    CONCURRENTLY. The migration has to be a no-op there, not a failure."""
    for statement in migrated.statements:
        migrated.execute(text(statement))
    migrated.commit()
    for name in INDEXES:
        assert _definition(migrated, name) is not None
