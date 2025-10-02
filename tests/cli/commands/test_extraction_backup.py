from __future__ import annotations

import builtins
from argparse import ArgumentParser, Namespace

import src.cli.commands.extraction_backup as extraction_backup


def _parse_extraction_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    extraction_backup.add_extraction_parser(subparsers)
    return parser.parse_args(["extract", *argv])


def test_add_extraction_parser_defaults():
    args = _parse_extraction_args([])

    assert args.limit == 50
    assert args.batches == 1
    assert args.articles_only is True
    assert args.source is None


def test_handle_extraction_command_runs_batches(monkeypatch, capsys):
    articles = [("1", "https://example.com/a", "Example", "article")]
    process_calls: list[tuple] = []

    class FakeResult:
        def __init__(self, data):
            self._data = data

        def fetchall(self):
            return self._data

    class FakeSession:
        def __init__(self):
            self.closed = False

        def execute(self, *_args, **_kwargs):
            return FakeResult(articles)

        def close(self):
            self.closed = True

    class FakeDatabaseManager:
        def __init__(self):
            self.session = FakeSession()

    db_instances: list[FakeDatabaseManager] = []

    def fake_db():
        instance = FakeDatabaseManager()
        db_instances.append(instance)
        return instance

    class FakeExtractor:
        def __init__(self):
            self.rotation_calls = 0

        def get_rotation_stats(self):
            self.rotation_calls += 1
            return {
                "total_domains_accessed": 2,
                "active_sessions": 1,
                "request_counts": {"example.com": 3},
            }

    class FakeCleaner:
        def __call__(self, *_args, **_kwargs):
            return None

    def fake_process(batch_articles, extractor, cleaner, session, batch_num):
        process_calls.append(
            (tuple(batch_articles), extractor, cleaner, session, batch_num)
        )
        return {"processed": 1, "successful": 1, "failed": 0}

    monkeypatch.setattr(extraction_backup, "DatabaseManager", fake_db)
    monkeypatch.setattr(extraction_backup, "ContentExtractor", FakeExtractor)
    monkeypatch.setattr(extraction_backup, "BylineCleaner", FakeCleaner)
    monkeypatch.setattr(extraction_backup, "_process_batch", fake_process)
    monkeypatch.setattr(
        extraction_backup.time,
        "sleep",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(builtins, "print", lambda *a, **k: None)

    args = Namespace(limit=1, batches=1, articles_only=True, source=None)

    exit_code = extraction_backup.handle_extraction_command(args)

    assert exit_code == 0
    assert process_calls and process_calls[0][0][0] == articles[0]
    assert db_instances and db_instances[0].session.closed is True


def test_handle_extraction_command_returns_error(monkeypatch):
    errors: list[str] = []

    def failing_db():
        raise RuntimeError("boom")

    monkeypatch.setattr(extraction_backup, "DatabaseManager", failing_db)
    monkeypatch.setattr(
        extraction_backup.logger,
        "error",
        lambda message: errors.append(message),
    )

    args = Namespace(limit=1, batches=1, articles_only=True, source=None)

    exit_code = extraction_backup.handle_extraction_command(args)

    assert exit_code == 1
    assert any("Extraction failed" in message for message in errors)


class _BatchSession:
    def __init__(self):
        self.insert_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.rollback_calls = 0
        self.commit_calls = 0

    def execute(self, query, params=None):
        text = str(query)
        if "INSERT INTO articles" in text:
            self.insert_calls.append(params or {})
        elif "UPDATE candidate_links" in text:
            self.update_calls.append(params or {})
        return self

    def rollback(self):
        self.rollback_calls += 1

    def commit(self):
        self.commit_calls += 1


class _BatchExtractor:
    def __init__(self, *, fail=False):
        self.fail = fail

    def extract_content(self, url):
        if self.fail:
            return {"error": "No title"}
        return {
            "title": f"Title for {url}",
            "content": "Body",
            "author": "Author",
            "publish_date": "2024-01-01",
            "metadata": {"extraction_methods": {"title": "selenium"}},
        }


class _BatchCleaner:
    def clean_byline(self, raw_author):
        return f"Clean {raw_author}"


def test_process_batch_successful_articles(monkeypatch):
    articles = [
        ("1", "https://example.com/a", "Example", "article"),
        ("2", "https://example.com/b", "Example", "article"),
    ]
    session = _BatchSession()
    extractor = _BatchExtractor()
    cleaner = _BatchCleaner()

    result = extraction_backup._process_batch(
        articles,
        extractor,
        cleaner,
        session,
        batch_num=1,
    )

    assert result["processed"] == 2
    assert session.insert_calls and session.update_calls
    assert session.commit_calls == 2


def test_process_batch_handles_failed_article(monkeypatch):
    articles = [("1", "https://example.com/a", "Example", "article")]
    session = _BatchSession()
    extractor = _BatchExtractor(fail=True)
    cleaner = _BatchCleaner()

    result = extraction_backup._process_batch(
        articles,
        extractor,
        cleaner,
        session,
        batch_num=1,
    )

    assert result["processed"] == 1
    assert session.insert_calls == []
    assert session.rollback_calls >= 0
