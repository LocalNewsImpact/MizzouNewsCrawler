"""`enrich run` could not be pointed at recent work.

`select_candidates` has taken a `since` floor on `created_at` since it was
written, and the command never passed it. So the only way to enrich the
articles a run had just extracted was `--limit`, and the selection is
`ORDER BY a.created_at` ASCENDING -- `--limit 191` takes the oldest 191 of
the backlog, which on 2026-09-07 was 82,781 eligible rows for one dataset.
The 191 wanted were the newest.

Working around it by hand is how the trap below gets sprung.
"""

import argparse
import inspect

from src.cli.commands import enrichment
from src.enrichment import repository


def _parse(argv):
    parser = argparse.ArgumentParser()
    enrichment.add_enrichment_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(argv)


def test_the_run_command_accepts_a_window():
    args = _parse(["enrich", "run", "--dataset", "mo", "--since", "2026-09-07"])

    assert args.since == "2026-09-07"


def test_the_window_reaches_the_query():
    """The floor exists in the SQL. What was missing was the command
    handing it over."""
    source = inspect.getsource(enrichment.handle_enrichment_command)

    assert 'since=getattr(args, "since", None)' in source
    assert "since" in inspect.signature(repository.select_candidates).parameters


def test_a_run_without_a_window_still_selects_everything():
    """The default has to stay what the cron does."""
    args = _parse(["enrich", "run", "--dataset", "mo"])

    assert args.since is None


def test_the_candidate_query_locks_the_rows_it_returns():
    """Why a hand-rolled selection deadlocks itself, recorded so the next
    person does not repeat it.

    `_CANDIDATE_SQL` ends in `FOR UPDATE OF a SKIP LOCKED`, so selecting
    candidates takes a row lock on every one of them. A caller that keeps
    the session open then blocks its own `UPDATE articles SET
    enrichment_attempts`, and the run dies on `canceling statement due to
    statement timeout` without writing anything.

    The command is correct because it selects inside a `with` block that
    closes. A script that calls `select_candidates` directly must do the
    same.
    """
    sql = str(repository._CANDIDATE_SQL)

    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql
