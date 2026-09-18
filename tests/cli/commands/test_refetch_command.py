"""The command that rewinds an article so its URL is fetched again.

The rewind itself is covered in tests/pipeline/test_a_body_can_be_fetched_again.py.
This covers the command around it: which articles a run selects, what it
refuses, and that `--list` and `--clear` reach the right code without writing.
"""

from __future__ import annotations

from argparse import Namespace

import pytest

from src.cli.commands import refetch as cmd


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = len(self._rows)

    def fetchall(self):
        return list(self._rows)

    def mappings(self):
        return iter(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        return _Result(self.answers.pop(0)) if self.answers else _Result()

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def db(monkeypatch):
    """Hand the command a session we can inspect."""
    sessions: list[_Session] = []

    def _install(session: _Session):
        sessions.append(session)

        class _DB:
            def get_session(self_inner):
                return session

        import src.models.database as database

        monkeypatch.setattr(database, "DatabaseManager", lambda *a, **k: _DB())
        return session

    return _install


def _args(**kw):
    base = dict(
        dataset=None,
        status=None,
        max_text_length=None,
        ids_file=None,
        by=None,
        reason=None,
        limit=None,
        list=False,
        clear=False,
        dry_run=False,
    )
    base.update(kw)
    return Namespace(**base)


class TestSelectingWhatToRewind:
    def test_neither_ids_nor_dataset_is_refused(self, db, capsys):
        db(_Session())
        assert cmd.handle_refetch_command(_args(by="d", reason="r")) == 1
        assert "--ids-file or --dataset" in capsys.readouterr().out

    def test_ids_come_from_the_file_one_per_line(self, tmp_path, db):
        path = tmp_path / "ids.txt"
        path.write_text("# a comment\na1\n\n  a2  \n")
        assert cmd._ids_from_file(str(path)) == ["a1", "a2"]

    def test_a_dataset_query_filters_by_status_and_length(self, db):
        session = db(_Session(answers=[[("a1",), ("a2",)]]))
        ids = cmd._ids_from_query(
            session,
            _args(dataset="WSU", status=["paywall"], max_text_length=400, limit=5),
        )
        assert ids == ["a1", "a2"]
        sql = session.statements[0]
        assert "d.slug = :dataset" in sql
        assert "a.status = ANY(:statuses)" in sql
        assert "coalesce(a.text_length, 0) < :max_len" in sql
        assert "LIMIT :limit" in sql

    def test_the_shortest_bodies_are_taken_first(self, db):
        """The least text is the strongest evidence the stored body is not the
        story, so a --limit run should spend itself on those."""
        session = db(_Session(answers=[[]]))
        cmd._ids_from_query(session, _args(dataset="WSU"))
        assert "ORDER BY coalesce(a.text_length, 0)" in session.statements[0]

    def test_a_dataset_query_without_filters_omits_them(self, db):
        session = db(_Session(answers=[[]]))
        cmd._ids_from_query(session, _args(dataset="WSU"))
        sql = session.statements[0]
        assert "ANY(:statuses)" not in sql
        assert ":max_len" not in sql
        assert "LIMIT" not in sql


class TestRefusals:
    def test_a_rewind_without_an_author_exits_nonzero(self, db, tmp_path, capsys):
        path = tmp_path / "ids.txt"
        path.write_text("a1\n")
        db(_Session(answers=[[]]))
        code = cmd.handle_refetch_command(
            _args(ids_file=str(path), by=None, reason="teaser")
        )
        assert code == 1
        assert "refused" in capsys.readouterr().out


class TestListing:
    def test_an_empty_queue_says_so(self, db, capsys):
        db(_Session(answers=[[]]))
        assert cmd.handle_refetch_command(_args(list=True)) == 0
        assert "nothing is waiting" in capsys.readouterr().out

    def test_it_shows_who_asked_and_why(self, db, capsys):
        """A body replaced with no record of who asked is indistinguishable
        from a body that was always wrong."""
        row = {
            "id": "a1",
            "url": "https://example.com/a1",
            "article_status": "paywall",
            "text_length": 212,
            "reason": "paywall teaser",
            "requested_by": "damon",
            "requested_at": "2026-09-18T00:00:00+00:00",
            "previous": "extracted",
        }
        db(_Session(answers=[[row]]))
        assert cmd.handle_refetch_command(_args(list=True, dataset="WSU")) == 0
        out = capsys.readouterr().out
        assert "1 article(s) rewound" in out
        assert "damon" in out
        assert "paywall teaser" in out
        assert "link was extracted" in out


class TestClearing:
    def test_clear_reports_how_many_links_went_back(self, db, tmp_path, capsys):
        path = tmp_path / "ids.txt"
        path.write_text("a1\n")
        db(_Session(answers=[[("a1",)]]))
        assert cmd.handle_refetch_command(_args(ids_file=str(path), clear=True)) == 0
        assert "links restored" in capsys.readouterr().out


class TestTheNormalPath:
    def test_a_rewind_reports_its_counts(self, db, tmp_path, capsys):
        path = tmp_path / "ids.txt"
        path.write_text("a1\n")
        row = {
            "id": "a1",
            "candidate_link_id": "l1",
            "link_status": "paywall",
            "url": "https://example.com/a1",
        }
        db(_Session(answers=[[row]]))
        code = cmd.handle_refetch_command(
            _args(ids_file=str(path), by="damon", reason="paywall teaser")
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "rewound:   1" in out

    def test_a_missing_article_is_named_rather_than_dropped(self, db, tmp_path, capsys):
        path = tmp_path / "ids.txt"
        path.write_text("nope\n")
        db(_Session(answers=[[]]))
        cmd.handle_refetch_command(
            _args(ids_file=str(path), by="damon", reason="teaser")
        )
        out = capsys.readouterr().out
        assert "missing:   1" in out
        assert "no such article: nope" in out

    def test_the_dry_run_says_it_wrote_nothing(self, db, tmp_path, capsys):
        path = tmp_path / "ids.txt"
        path.write_text("a1\n")
        row = {
            "id": "a1",
            "candidate_link_id": "l1",
            "link_status": "paywall",
            "url": "https://example.com/a1",
        }
        session = db(_Session(answers=[[row]]))
        cmd.handle_refetch_command(
            _args(ids_file=str(path), by="d", reason="r", dry_run=True)
        )
        assert "nothing written" in capsys.readouterr().out
        assert session.commits == 0


class TestTheParser:
    def test_by_and_reason_are_offered(self):
        import argparse

        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers()
        cmd.add_refetch_articles_parser(subs)
        args = parser.parse_args(
            ["refetch-articles", "--ids-file", "x", "--by", "d", "--reason", "r"]
        )
        assert args.by == "d"
        assert args.reason == "r"
        assert args.func is cmd.handle_refetch_command
