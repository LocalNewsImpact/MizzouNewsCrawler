"""A column that does not exist aborts the transaction, not just the query.

`_get_persistent_patterns` selected `pattern_text` and `boundary_score`
from `persistent_boilerplate_patterns`. Neither column exists -- the text
is `text_content` and the confidence is `confidence_score` -- so Postgres
answered 42703, and an error inside a transaction ABORTS it. Every later
statement in that transaction is then refused with 25P02, "current
transaction is aborted, commands ignored until end of transaction block".

The caller caught the first error, logged "Domain analysis failed" and
carried on. So on 2026-09-13 a boilerplate query took out the rework
settle that ran later in the same transaction: seven fetched links stayed
recorded as owing work, and the pod exited 0.

These read each raw SQL statement's column list against the model that
owns the table, so a name that does not exist fails here rather than in a
pod at 3am.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _columns(table):
    """The columns a table has, from the SQLAlchemy models."""
    from src.models import Base

    for mapped in Base.registry.mappers:
        if mapped.class_.__tablename__ == table:
            return {c.name for c in mapped.columns}
    return None


#: Every table a raw SELECT in these modules reads, with the columns it
#: asks for. Read as text: the statements are f-strings and templates, so
#: parsing them fully is not worth it -- the simple `SELECT a, b FROM t`
#: shape is where this class of mistake lives.
MODULES = (
    "src/utils/content_cleaner_balanced.py",
    "src/pipeline/rework.py",
)

#: `SELECT a, b FROM t` and nothing cleverer. A joined statement attributes
#: columns to tables this cannot know, and a subquery or a function call is
#: not what this is for: the mistake it catches is a plain column name that
#: does not exist.
PATTERN = re.compile(
    r"SELECT\s+([A-Za-z0-9_,\s]+?)\s+FROM\s+([a-z_]+)\b([^;\"']*)", re.IGNORECASE
)


def _statements():
    for name in MODULES:
        text = (ROOT / name).read_text()
        for columns, table, rest in PATTERN.findall(text):
            if _columns(table) is None:
                continue  # a table this repository does not model
            head = rest[:400].upper()
            if " JOIN " in head or "," in table:
                continue  # more than one table: not this test's business
            named = [
                c.strip()
                for c in columns.split(",")
                # `SELECT 1 FROM ...` in an EXISTS asks for no column, and
                # an alias or a qualified name is not a bare column either.
                if c.strip()
                and "(" not in c
                and "." not in c
                and not c.strip().isdigit()
                and c.strip() != "*"
            ]
            if named:
                yield name, table, named


CASES = list(_statements())


def test_there_are_statements_to_check():
    assert CASES, "no raw SELECTs found; the pattern or the module list is wrong"


@pytest.mark.parametrize(
    "module,table,columns", CASES, ids=[f"{m.split('/')[-1]}:{t}" for m, t, _ in CASES]
)
def test_every_column_a_select_names_exists(module, table, columns):
    have = _columns(table)
    missing = [c for c in columns if c not in have and c != "*"]
    assert missing == [], (
        f"{module} selects {missing} from {table}, which has "
        f"{sorted(have)}. Postgres answers 42703 and ABORTS the "
        "transaction: every later statement in it fails with 25P02."
    )


def test_the_pattern_query_reads_the_columns_it_needs():
    """Named directly, because this is the one that broke and the mapping
    from what the code wants to what the table calls it is not obvious:
    the pattern's text is `text_content`, its confidence is
    `confidence_score`."""
    source = (ROOT / "src/utils/content_cleaner_balanced.py").read_text()
    assert "SELECT text_content, pattern_type, confidence_score" in source
    assert "pattern_text," not in source.split("FROM persistent_boilerplate")[0][-200:]
