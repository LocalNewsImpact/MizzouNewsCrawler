"""`extraction_method` decides whether a publisher is fetched with a
browser, and for the life of the column almost nothing could read it.

The column was created with a server default whose quotes were part of
the string, so the stored value was six characters where four were meant,
and every row inserted since carried them.

One place compares the value, and it is the place that matters: the
escalation in `src/crawler/__init__.py` that switches a publisher to
Selenium after a fetch meets bot protection or a JavaScript wall. Its
clause is `extraction_method = 'http' OR extraction_method IS NULL`,
which matched 32 of 1,148 sources. It had fired four times ever.

What that cost: 45 articles across five publishers whose stored body was
the static shell of a JavaScript-rendered page -- 5,308 bytes whose only
text is a registration form's country dropdown, byte-identical across
four domains. Every one had been fetched without a browser and never
with one, because the switch that would have changed that could not see
them.

These guard the SHAPE of the value rather than the migration: the
migration can only fix the rows that exist, and a new writer that quoted
its input would refill the column with nothing to say so.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = (
    ROOT / "alembic/versions/w8x9y0z1a2b3_extraction_method_was_stored_quoted.py"
)
CRAWLER = ROOT / "src/crawler/__init__.py"

#: The values the column may hold, unquoted.
METHODS = {"http", "selenium", "unblock", "trafilatura"}

#: The bug, as it appears in source: a default whose quotes are data.
QUOTED_DEFAULT = 'server_default="' + "'http'" + '"'
GOOD_DEFAULT = 'server_default="http"'


def _code(path):
    """The file without its module docstring.

    These files explain the bug by quoting it, so a search over the whole
    text finds the explanation and reports the fault it describes -- which
    is what the first version of this file did to itself.
    """
    body = path.read_text()
    stripped = body.lstrip()
    if stripped.startswith('"""'):
        start = body.index('"""')
        end = body.index('"""', start + 3) + 3
        return body[:start] + body[end:]
    return body


def test_the_migration_sets_an_unquoted_default():
    body = _code(MIGRATION)
    assert GOOD_DEFAULT in body
    assert QUOTED_DEFAULT not in body


def test_the_migration_strips_the_quotes_idempotently():
    """`btrim` leaves an unquoted value alone, so a re-run costs nothing
    and a partially-fixed table is finished rather than double-stripped."""
    assert "btrim(extraction_method" in _code(MIGRATION)


def test_the_downgrade_does_not_restore_the_bug():
    """A downgrade that puts the quotes back makes the escalation inert
    again, silently, and a downgrade is not a thing anybody watches."""
    down = _code(MIGRATION).split("def downgrade()")[1]
    assert QUOTED_DEFAULT not in down
    assert GOOD_DEFAULT in down


def test_the_escalation_still_compares_against_the_unquoted_form():
    """If this clause is ever rewritten to match the quoted value, the
    fix becomes the bug. The clause is the whole reason the column
    exists."""
    body = _code(CRAWLER)
    assert "extraction_method = 'http' OR extraction_method IS NULL" in body


@pytest.mark.parametrize("method", sorted(METHODS))
def test_no_writer_quotes_the_value(method):
    """Every literal the code assigns is bare. A writer that wrapped its
    input in quotes would refill the column one publisher at a time, and
    the only symptom would be a publisher quietly never escalated."""
    quoted = '"' + "'" + method + "'" + '"'
    for path in (
        CRAWLER,
        ROOT / "src/crawler/proxy_router.py",
        ROOT / "src/crawler/fetch_plan.py",
    ):
        assert quoted not in _code(path), f"{path.name} quotes {method}"


def test_the_column_is_read_by_something_that_would_notice():
    """The value gates whether HTTP methods are skipped entirely. A
    quoted value falls through every branch and the publisher is fetched
    the ordinary way -- which is exactly what happened to five publishers
    serving JavaScript-rendered pages.

    Asked of the decision rather than of the source text. This used to match
    `skip_http_methods = extraction_method in {...}` with a regex, which broke
    when that moved into `src/crawler/fetch_plan.py` without the behaviour
    changing at all."""
    from src.crawler.fetch_plan import BROWSER_ONLY_METHODS

    assert BROWSER_ONLY_METHODS, "the method no longer gates HTTP fetching"
    unknown = set(BROWSER_ONLY_METHODS) - METHODS
    assert not unknown, f"{unknown} is not a known method"


@pytest.mark.parametrize("method", sorted({"selenium", "unblock"}))
def test_a_quoted_value_does_not_reach_the_browser(method):
    """The failure itself: the column held six characters where four were
    meant, so the comparison missed and the publisher was fetched without a
    browser for the life of the column. A test that only checks the literals
    are spelled correctly would not have caught it."""
    from src.crawler.fetch_plan import plan_fetch

    def plan(value):
        return plan_fetch(
            credentialed=False,
            extraction_method=value,
            protection_type=None,
            cloudscraper_available=False,
            amp_supported=False,
        )

    assert plan(method).skip_http_methods is True
    assert plan(f"'{method}'").skip_http_methods is False
