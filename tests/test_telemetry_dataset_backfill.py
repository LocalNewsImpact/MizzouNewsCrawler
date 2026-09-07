"""The backfill recovers a dataset it can prove, and leaves the rest null.

617k telemetry rows predate the `dataset_id` column. Most of them can be
resolved exactly, because the dataset lives on `candidate_links` and each
table reaches a link by foreign key. One cannot: `extraction_telemetry_v2`
holds only `url`, so it joins on URL text, and a URL discovered under two
datasets has no single right answer.

The rule these tests hold to is that a null is a better record than a
guess. A wrong dataset does not read as missing data -- it reads as a
fact, and it would put one corpus's extraction work under another's name.
"""

import re

import pytest

from src.cli.commands.telemetry_dataset_backfill import (
    BACKFILL_SOURCES,
    DATE_COLUMN,
    _date_clause,
)


def test_every_backfilled_table_knows_how_to_date_its_rows():
    """--since/--until has to mean something for each table, and the
    column is not the same one everywhere: enrichment dates by
    `enriched_at`, the rest by `created_at`."""
    assert set(BACKFILL_SOURCES) == set(DATE_COLUMN)


def test_the_url_join_refuses_an_ambiguous_url():
    """`extraction_telemetry_v2` is the one table without a foreign key to
    a candidate link. Joining on URL text is exact only where the URL
    belongs to one dataset, so the statement counts the distinct datasets
    for that URL and requires exactly one."""
    join = BACKFILL_SOURCES["extraction_telemetry_v2"]["join"]

    # "No other dataset claims this URL", which is the same question
    # `count(DISTINCT ...) = 1` asked and answers it without reading every
    # match. See test_the_url_guard_stops_at_the_first_disagreement.
    assert "c2.dataset_id <> cl.dataset_id" in join
    assert "NOT EXISTS" in join


def test_the_foreign_key_joins_do_not_guess():
    """Every other table reaches the dataset through an id, so none of
    them needs the ambiguity guard -- and none of them should match on
    URL text, which is what makes the guard necessary."""
    for table, source in BACKFILL_SOURCES.items():
        if table == "extraction_telemetry_v2":
            continue
        assert ".url" not in source["join"], f"{table} should join on an id"


@pytest.mark.parametrize(
    "table",
    ["verification_telemetry", "verification_jobs", "jobs"],
)
def test_per_run_tables_are_not_backfilled(table):
    """These describe a run rather than a record and hold no link back to
    one. There is nothing to recover, so the command does not pretend to."""
    assert table not in BACKFILL_SOURCES


@pytest.mark.parametrize(
    "since,until,expected",
    [
        (None, None, 0),
        ("2026-01-01", None, 1),
        (None, "2027-01-01", 1),
        ("2026-01-01", "2027-01-01", 2),
    ],
)
def test_the_date_filter_names_a_parameter_only_when_it_has_one(since, until, expected):
    """The same rule the work queue had to learn: a bare parameter compared
    to NULL cannot be typed by pg8000 and fails 42P18 before the statement
    runs. Appending the clause avoids the construct rather than casting
    around it."""
    clause, params = _date_clause("url_verifications", since, until)

    assert len(params) == expected
    assert "IS NULL OR" not in clause
    for name in params:
        assert clause.count(f":{name}") == 1, "a parameter mentioned twice"


def test_no_backfill_statement_uses_the_shape_that_fails_to_plan():
    import inspect

    import src.cli.commands.telemetry_dataset_backfill as module

    source = "\n".join(
        line
        for line in inspect.getsource(module).splitlines()
        if not line.lstrip().startswith("#")
    )

    assert not re.findall(r":(\w+)\s+IS\s+NULL\s+OR", source)


def test_a_real_run_does_not_count_before_it_writes():
    """The count is the same scan as the work.

    Running it first doubled every backfill, and on `extraction_telemetry_v2`
    the count alone exceeded the two-minute `statement_timeout` and killed
    the production run before a single row was written. A real run reports
    what it wrote, which is the more truthful number anyway.
    """
    import inspect

    from src.cli.commands.telemetry_dataset_backfill import (
        handle_telemetry_dataset_backfill_command,
    )

    source = inspect.getsource(handle_telemetry_dataset_backfill_command)
    counted = source.index("_count_pending(")
    guarded = source.index("if args.dry_run:")

    assert guarded < counted, "the count must sit inside the dry-run branch"


def test_the_url_guard_stops_at_the_first_disagreement():
    """`count(DISTINCT c2.dataset_id) = 1` had to read every candidate link
    sharing the URL before it could compare. NOT EXISTS gives the same
    answer -- no other dataset claims this URL -- and stops at the first
    row that disagrees. That is the difference between a batch that times
    out and one that takes seconds."""
    join = BACKFILL_SOURCES["extraction_telemetry_v2"]["join"]

    assert "count(DISTINCT" not in join
    assert "c2.dataset_id <> cl.dataset_id" in join


def test_the_batches_are_given_longer_than_the_default_to_run():
    """A batch over 193k rows is a bigger statement than the two-minute
    session default allows."""
    import inspect

    from src.cli.commands import telemetry_dataset_backfill

    source = inspect.getsource(telemetry_dataset_backfill._fill)
    assert "statement_timeout" in source
