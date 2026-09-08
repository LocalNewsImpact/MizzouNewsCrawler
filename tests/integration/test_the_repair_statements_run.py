"""The repair statements have to run, not merely read correctly.

`repair-byline-surnames` shipped and failed on its first production run:
42601, syntax error at ":". The statement carried `:note::jsonb`, and
pg8000 rewrites named parameters to positional ones -- the `::` right
after one does not survive that. The same driver quirk is behind the
42P18 failures documented in services/work_queue.py.

The unit tests passed. They checked the pure function that rebuilds a
name, and they checked the SQL as *text* -- that it mentioned the right
columns and not `status`. Neither asks a database to parse it, so a
statement that no Postgres would accept read as correct all the way into
production.

These execute. Against SQLite where the dialect allows it, and against
Postgres when TEST_DATABASE_URL is set, which is where the driver that
broke it actually lives.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from src.cli.commands.byline_surname_repair import FIND_SQL, REPAIR_SQL
from src.cli.commands.link_status_repair import COUNT_SQL
from src.cli.commands.link_status_repair import REPAIR_SQL as LINK_REPAIR_SQL
from src.cli.commands.rot47_body_repair import FIND_SQL as ROT47_FIND_SQL
from src.cli.commands.rot47_body_repair import REPAIR_SQL as ROT47_REPAIR_SQL

POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_TEST_URL and "postgres" in POSTGRES_TEST_URL

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

#: Every statement a repair command sends, with parameters shaped as the
#: command sends them. A statement absent from here is one nothing has
#: ever asked a database to parse.
STATEMENTS = [
    ("byline find", FIND_SQL, {"shapes": ['["fox"]']}),
    (
        "byline repair",
        REPAIR_SQL,
        {
            "name": "Jeffrey Fox",
            "rewind": "cleaned",
            "id": "no-such-article",
            "note": '{"was": "Jeffrey", "rebuilt": "Jeffrey Fox"}',
        },
    ),
    (
        "rot47 find",
        ROT47_FIND_SQL,
        {"since": None, "until": None, "limit": 1},
    ),
    (
        "rot47 repair",
        ROT47_REPAIR_SQL,
        {
            "id": "no-such-article",
            "content": "decoded",
            "text": "decoded",
            "text_hash": "abc",
            "excerpt": "decoded",
        },
    ),
    ("link count", COUNT_SQL, {"statuses": ["enriched"]}),
    (
        "link repair",
        LINK_REPAIR_SQL,
        {"statuses": ["enriched"], "new_status": "extracted", "batch": 1},
    ),
]


@pytest.fixture
def postgres_engine():
    if not HAS_POSTGRES:
        pytest.skip("PostgreSQL test database not configured (set TEST_DATABASE_URL)")
    return create_engine(POSTGRES_TEST_URL)


@pytest.mark.parametrize(
    "name,statement,params", STATEMENTS, ids=[s[0] for s in STATEMENTS]
)
def test_postgres_parses_the_statement(postgres_engine, name, statement, params):
    """PREPARE asks the server to parse and plan without running it.

    The tables need not hold anything -- a syntax error, an unknown
    column or a parameter the driver mangles is raised here, which is
    every way these statements have actually failed.
    """
    with postgres_engine.connect() as connection:
        # Executed in a transaction that is rolled back: `link repair`
        # and the two repairs are UPDATEs, and this is a real database.
        transaction = connection.begin()
        try:
            connection.execute(statement, params)
        finally:
            transaction.rollback()


def test_no_bound_parameter_is_followed_by_a_cast():
    """The shape that failed, banned by inspection as well as by
    execution: `:param::type` parses locally and dies under pg8000, so a
    statement carrying one must not reach production even if no
    integration database is configured to catch it.
    """
    import re

    for name, statement, _params in STATEMENTS:
        # Comments stripped first: the note explaining this rule quotes
        # the pattern it forbids, and scanning the raw text made the
        # explanation fail the test it explains.
        rendered = re.sub(r"--[^\n]*", "", str(statement))
        assert not re.search(r":[a-z_]+::", rendered), (
            f"{name}: a bound parameter is followed by `::`. Use "
            f"CAST(:param AS type) -- pg8000 rewrites the parameter and "
            f"the cast does not survive it."
        )
