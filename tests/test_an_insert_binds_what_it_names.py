"""Every raw INSERT binds one value for each column it names.

WHY THIS EXISTS. `refresh_candidates` builds its INSERT from two lists written in
two separate strings -- the columns, then the values -- and they drifted:
`mismatches` was added to the values and not to the columns. Every refresh then
raised

    A value is required for bind parameter 'mismatches'

and the nightly byline queue would have failed behind its `continueOn: failed`,
which is to say silently.

WHY THE UNIT TESTS DID NOT CATCH IT. There are twelve tests around that function
and every one passes a `MagicMock` session. A mock accepts any SQL string and any
parameter dict, so the statement is never checked by anything: the tests assert on
the parameters, and the parameters were right. The statement is Postgres-only
(`gen_random_uuid()::text`, a quoted `"group"`, `ANY(:statuses)`), so the SQLite
suite could not have run it either.

WHY IT REACHED MAIN. The edit that should have added the column was a
`str.replace` that matched nothing -- the formatter had reflowed the line it was
looking for -- and a replacement that matches nothing reports success.

So this reads the source. It needs no database, runs in milliseconds, and covers
every raw INSERT in `src/` rather than the one that broke: a guard written for a
single statement would not have been there for the next one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Where a statement starts. Everything after it is read by hand: a regular
#: expression cannot match balanced parentheses, and an earlier version of this
#: file ran past the closing bracket into the rest of the module, reporting an
#: INSERT of 10 columns as binding 49 values.
_START = re.compile(r"INSERT\s+INTO\s+(?P<table>[\w.\"]+)\s*\(", re.I)


def _balanced(text: str, start: int) -> tuple[str, int]:
    """The contents of the bracket opening at `start`, and where it closes."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index
    return "", -1


def _split(items: str) -> list[str]:
    """Top-level commas only, so `coalesce(a, b)` stays one item."""
    out, depth, current = [], 0, []
    for char in items:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            out.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if "".join(current).strip():
        out.append("".join(current).strip())
    return [item for item in out if item]


def _statements():
    """Every raw INSERT in `src/`, as `(file, table, columns, values)`.

    The SQL is built from adjacent Python string literals, so the quotes and the
    newlines between them are stripped before the two lists are read. A `"group"`
    keeps its SQL quoting -- it is a reserved word -- and is compared without it.

    A statement whose VALUES cannot be read as a simple list is SKIPPED rather
    than failed: multi-row inserts and `INSERT ... SELECT` are legitimate and are
    not what this checks. A guard that cries wolf is one nobody reads.
    """
    found = []
    for path in sorted(ROOT.joinpath("src").rglob("*.py")):
        source = path.read_text()
        if "INSERT INTO" not in source:
            continue
        # A comment line may sit BETWEEN two string literals of one statement
        # (`extraction.py` explains a subquery that way), so those go before the
        # literals are joined -- otherwise the statement is read with a hole in
        # the middle.
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        flattened = re.sub(r"[\"']\s*\n\s*[\"']", "", code)
        for match in _START.finditer(flattened):
            columns_text, closed = _balanced(flattened, match.end() - 1)
            if closed < 0:
                continue
            after = flattened[closed + 1 : closed + 40]
            values_at = after.upper().find("VALUES")
            if values_at < 0:
                # `INSERT ... SELECT`, or a statement built some other way.
                continue
            opens = flattened.find("(", closed + 1 + values_at)
            values_text, _ = _balanced(flattened, opens)
            columns = [c.strip('"').strip("'") for c in _split(columns_text)]
            values = _split(values_text)
            if not columns or not values:
                continue
            # An ellipsis means prose, not SQL: the module docstrings show this
            # exact mistake as the thing to avoid, and a guard that fails on a
            # worked example teaches people to ignore it.
            if any("..." in item for item in columns + values):
                continue
            found.append(
                (
                    path.relative_to(ROOT).as_posix(),
                    match.group("table").strip('"'),
                    columns,
                    values,
                )
            )
    return found


def test_there_are_raw_inserts_to_check():
    """A guard that finds nothing is a guard that has stopped working -- if the
    pattern stops matching, every test below passes vacuously."""
    assert _statements(), "no raw INSERT found in src/; the pattern has gone stale"


@pytest.mark.parametrize("statement", _statements(), ids=lambda s: f"{s[0]}:{s[1]}")
def test_it_binds_one_value_for_every_column(statement):
    path, table, columns, values = statement
    assert len(columns) == len(values), (
        f"{path}: INSERT INTO {table} names {len(columns)} columns and binds "
        f"{len(values)} values.\n  columns: {columns}\n  values:  {values}"
    )


@pytest.mark.parametrize("statement", _statements(), ids=lambda s: f"{s[0]}:{s[1]}")
def test_every_bind_parameter_is_spelled_once(statement):
    """The same parameter twice in one statement is a copied line whose name was
    not changed -- the shape that writes one column's value into another."""
    path, table, _columns, values = statement
    binds = [v for v in values if v.startswith(":")]
    duplicated = {b for b in binds if binds.count(b) > 1}
    assert not duplicated, f"{path}: INSERT INTO {table} binds {duplicated} twice"
