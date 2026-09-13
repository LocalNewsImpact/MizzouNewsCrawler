"""The same story at two URLs leaves two records, and both say what they are.

A publisher serves one article at `http` and `https`, with and without
`www`, with a trailing slash, with a tracking query. Each variant is
discovered as its own candidate link, and `articles.url` is unique, so only
the first extracted gets an article row.

What happened to the second one was invisible, two ways:

  `scripts/cleanup_url_duplicates.py` DELETED the newer duplicate article
  and left its link at `extracted`, pointing at nothing. 1,458 March links
  were in that state; the reporting called them "Link says extracted, no
  article" and it took a day to trace the hole to a script run by hand
  months earlier.

  Extraction's insert is `ON CONFLICT DO NOTHING`, so a variant extracted
  second wrote no row -- and the link was left at `article`, to be fetched
  again on the next run, and the next.

Nothing is deleted now. The link is marked `duplicate` and says which
article survived.
"""

import inspect
from pathlib import Path

from src.cli.commands import duplicates

ROOT = Path(__file__).resolve().parent.parent


def test_a_duplicate_is_marked_and_never_deleted():
    """Deleting is what made this invisible. The link is the evidence that
    the publisher served the URL and the crawler found it."""
    source = inspect.getsource(duplicates)
    assert "UPDATE candidate_links SET status" in source
    # The executable statements only: the docstrings say the word "delete"
    # a great deal, because saying why is the point.
    statements = [
        line for line in source.splitlines() if not line.strip().startswith("#")
    ]
    sql = " ".join(statements).upper()
    assert "DELETE FROM" not in sql


def test_the_mark_names_the_article_that_survived():
    """ "Duplicate" on its own is another dead end: the next person has to
    find the story it duplicates."""
    source = inspect.getsource(duplicates.mark)
    assert "article {survivor}" in source


def test_the_status_is_selected_by_no_stage():
    """`duplicate` must not be a status extraction, classification or
    enrichment reads, or the link comes straight back."""
    from lnic_contracts import pipeline_rework as contract

    for stage in contract.STAGES:
        assert duplicates.DUPLICATE not in contract.selects(stage), stage


def test_normalisation_strips_everything_that_makes_one_story_look_like_two():
    """The old script stripped only the scheme and `www.`, which is why 343
    of the links it orphaned could not be matched to their survivor
    afterwards."""
    n = duplicates.NORMALISE
    assert "^https?://(www\\.)?" in n, "scheme and www"
    assert "[?#].*$" in n, "query and fragment"
    assert "/+$" in n, "trailing slash"
    assert "lower(" in n, "case"


def test_both_sides_of_the_comparison_are_normalised():
    """Normalising one side only matches nothing."""
    source = inspect.getsource(duplicates.orphaned_links)
    assert source.count("_norm(") == 2


def test_it_works_one_source_at_a_time():
    """Normalising every URL against every other is a full scan of 160,000
    articles and does not finish inside a statement timeout -- measured,
    twice, while investigating this. A publisher's duplicates are its own
    URLs."""
    source = inspect.getsource(duplicates.orphaned_links)
    assert "cl.source_id = :source_id" in source
    assert "c2.source_id = :source_id" in source


def test_the_oldest_survivor_wins():
    """The rule the corpus was built on, and the one the old script used."""
    source = inspect.getsource(duplicates.orphaned_links)
    assert "ORDER BY m.id, s.created_at" in source


def test_nothing_is_written_without_apply():
    source = inspect.getsource(duplicates.handle_duplicates_command)
    assert "if args.apply:" in source
    assert "nothing written" in source


def test_extraction_marks_a_conflicting_insert_as_a_duplicate():
    """Leaving the link at `article` meant fetching the same page every
    night to reach the same conflict."""
    body = (ROOT / "src/cli/commands/extraction.py").read_text()
    branch = body.split("inserted = getattr(insert_result")[1].split("else:")[0]
    assert "from src.cli.commands.duplicates import DUPLICATE" in branch
    assert "UPDATE candidate_links SET status" in branch
    assert "already holds" in branch


def test_the_old_script_is_the_thing_being_replaced():
    """It deletes, and it normalises too little. Kept for the record, not
    to be run: this is what to run instead."""
    old = (ROOT / "scripts/cleanup_url_duplicates.py").read_text()
    assert "DELETE FROM articles" in old, "if this stops deleting, update the docs"


# --- the command itself, run ------------------------------------------------------


def _session(rows_by_source=None, rowcount=1):
    """A session whose SELECTs answer with the rows a test names."""
    from unittest.mock import Mock

    rows_by_source = rows_by_source or {}

    def execute(statement, params=None):
        sql = str(statement)
        result = Mock()
        result.rowcount = rowcount
        if "FROM sources" in sql:
            result.fetchall.return_value = [(s,) for s in rows_by_source]
        elif "WITH mine AS" in sql:
            result.fetchall.return_value = rows_by_source.get(
                (params or {}).get("source_id"), []
            )
        else:
            result.fetchall.return_value = []
        return result

    session = Mock()
    session.execute.side_effect = execute
    return session


def _args(**kw):
    from types import SimpleNamespace

    defaults = {"source": None, "apply": False, "limit_sources": None}
    return SimpleNamespace(**{**defaults, **kw})


def _patched(session):
    from unittest.mock import MagicMock, patch

    db = MagicMock()
    db.get_session.return_value.__enter__.return_value = session
    db.get_session.return_value.__exit__.return_value = False
    return patch("src.models.database.DatabaseManager", return_value=db)


def test_a_dry_run_reports_and_writes_nothing(capsys):
    session = _session({"src-a": [("l1", "http://x/a", "art-1")]})
    with _patched(session):
        assert duplicates.handle_duplicates_command(_args()) == 0
    out = capsys.readouterr().out
    assert "duplicates found: 1" in out
    assert "nothing written" in out
    assert not any(
        "UPDATE candidate_links" in str(c.args[0])
        for c in session.execute.call_args_list
    ), "a dry run must not write"


def test_apply_marks_each_duplicate(capsys):
    session = _session(
        {"src-a": [("l1", "http://x/a", "art-1"), ("l2", "http://x/b", "art-2")]}
    )
    with _patched(session):
        assert duplicates.handle_duplicates_command(_args(apply=True)) == 0
    out = capsys.readouterr().out
    assert "duplicates found: 2" in out
    assert "marked `duplicate`: 2" in out


def test_one_source_can_be_named(capsys):
    """A publisher at a time, for a bounded first pass."""
    session = _session({"src-a": [("l1", "http://x/a", "art-1")]})
    with _patched(session):
        duplicates.handle_duplicates_command(_args(source="src-a"))
    assert not any(
        "FROM sources" in str(c.args[0]) for c in session.execute.call_args_list
    ), "it should not enumerate sources when given one"


def test_the_source_list_can_be_capped(capsys):
    session = _session({"a": [], "b": [], "c": []})
    with _patched(session):
        duplicates.handle_duplicates_command(_args(limit_sources=1))
    asked = [
        (c.kwargs or {}).get("source_id") or (c.args[1] or {}).get("source_id")
        for c in session.execute.call_args_list
        if len(c.args) > 1 and isinstance(c.args[1], dict)
    ]
    assert len([a for a in asked if a]) <= 1


def test_a_source_with_no_duplicates_is_silent(capsys):
    session = _session({"src-a": []})
    with _patched(session):
        duplicates.handle_duplicates_command(_args(apply=True))
    assert "duplicates found: 0" in capsys.readouterr().out


def test_marking_nothing_writes_nothing():
    session = _session()
    assert duplicates.mark(session, []) == 0
    session.execute.assert_not_called()
    session.commit.assert_not_called()


def test_the_parser_offers_what_the_command_needs():
    """Built through argparse, as the CLI builds it: a flag the handler
    reads and the parser never defines is an AttributeError in production."""
    import argparse

    parser = argparse.ArgumentParser()
    duplicates.add_duplicates_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["duplicates"])

    assert args.source is None
    assert args.apply is False, "writing is never the default"
    assert args.limit_sources is None

    args = parser.parse_args(
        ["duplicates", "--source", "s1", "--apply", "--limit-sources", "3"]
    )
    assert (args.source, args.apply, args.limit_sources) == ("s1", True, 3)
