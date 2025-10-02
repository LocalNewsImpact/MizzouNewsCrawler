from __future__ import annotations

from argparse import ArgumentParser, Namespace
from collections import defaultdict

import src.cli.commands.extraction as extraction


def _parse_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    extraction.add_extraction_parser(subparsers)
    return parser.parse_args(["extract", *argv])


def test_add_extraction_parser_defaults():
    args = _parse_args([])

    assert args.limit == 10
    assert args.batches == 1
    assert args.source is None
    assert args.func is extraction.handle_extraction_command


def test_handle_extraction_command_success(monkeypatch):
    calls = {
        "process": 0,
        "post_clean_domains": None,
        "closed": False,
    }

    class FakeExtractor:
        def __init__(self):
            self.closed = False

        def get_driver_stats(self):
            return {
                "has_persistent_driver": True,
                "driver_reuse_count": 3,
                "driver_creation_count": 1,
            }

        def close_persistent_driver(self):
            calls["closed"] = True

    class FakeTelemetry:
        def record_extraction(self, *_args, **_kwargs):
            return None

    def fake_process(
        args,
        extractor,
        byline_cleaner,
        telemetry,
        per_batch,
        batch_num,
        host_403_tracker,
        domains_for_cleaning,
    ):
        calls["process"] += 1
        domains_for_cleaning.setdefault("example.com", []).append(
            f"article-{batch_num}"
        )
        return {"processed": 1}

    def fake_post_clean(domains):
        calls["post_clean_domains"] = domains

    monkeypatch.setattr(extraction, "ContentExtractor", FakeExtractor)
    monkeypatch.setattr(extraction, "BylineCleaner", lambda: object())
    monkeypatch.setattr(
        extraction,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(),
    )
    monkeypatch.setattr(extraction, "_process_batch", fake_process)
    monkeypatch.setattr(
        extraction,
        "_run_post_extraction_cleaning",
        fake_post_clean,
    )
    monkeypatch.setattr(extraction.time, "sleep", lambda *_a, **_k: None)

    args = Namespace(batches=2, limit=1, source=None)

    exit_code = extraction.handle_extraction_command(args)

    assert exit_code == 0
    assert calls["process"] == 2
    assert calls["closed"] is True
    assert calls["post_clean_domains"] == {
        "example.com": ["article-1", "article-2"]
    }


def test_handle_extraction_command_handles_exception(monkeypatch):
    errors = []

    class FakeExtractor:
        def __init__(self):
            self.closed = False

        def get_driver_stats(self):
            return {"has_persistent_driver": False}

        def close_persistent_driver(self):
            self.closed = True
            errors.append("closed")

    class FakeTelemetry:
        def record_extraction(self, *_args, **_kwargs):
            return None

    def failing_process(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(extraction, "ContentExtractor", FakeExtractor)
    monkeypatch.setattr(extraction, "BylineCleaner", lambda: object())
    monkeypatch.setattr(
        extraction,
        "ComprehensiveExtractionTelemetry",
        lambda: FakeTelemetry(),
    )
    monkeypatch.setattr(extraction, "_process_batch", failing_process)
    monkeypatch.setattr(
        extraction.logger,
        "exception",
        lambda msg: errors.append(msg),
    )
    monkeypatch.setattr(extraction.time, "sleep", lambda *_a, **_k: None)

    args = Namespace(batches=1, limit=1, source=None)

    exit_code = extraction.handle_extraction_command(args)

    assert exit_code == 1
    assert "Extraction failed" in errors
    assert "closed" in errors


def test_format_cleaned_authors_normalizes_output():
    assert extraction._format_cleaned_authors([" Alice ", ""]) == "Alice"
    assert extraction._format_cleaned_authors(["Bob", "Carol"]) == "Bob, Carol"
    assert extraction._format_cleaned_authors([]) is None
    assert extraction._format_cleaned_authors([None, "   "]) is None


class _FakeSession:
    def __init__(self, rows):
        self._rows_queue = [rows]
        self.insert_calls: list[dict] = []
        self.update_calls: list[tuple] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def execute(self, query, params=None):
        if params and "limit_with_buffer" in params:
            data = self._rows_queue.pop(0) if self._rows_queue else []
            return _FakeResult(data)

        if query is extraction.ARTICLE_INSERT_SQL:
            self.insert_calls.append(params or {})
            return _FakeResult([])
        if query is extraction.CANDIDATE_STATUS_UPDATE_SQL:
            self.update_calls.append(("candidate", params))
            return _FakeResult([])
        if query is extraction.PAUSE_CANDIDATE_LINKS_SQL:
            self.update_calls.append(("pause", params))
            return _FakeResult([])
        if query is extraction.ARTICLE_UPDATE_SQL:
            self.update_calls.append(("article", params))
            return _FakeResult([])
        if query is extraction.ARTICLE_STATUS_UPDATE_SQL:
            self.update_calls.append(("status", params))
            return _FakeResult([])

        return _FakeResult([])

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.closed = True


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]


class _FakeDBManager:
    def __init__(self, session):
        self.session = session


def test_process_batch_success_path(monkeypatch):
    rows = [
        (
            "cand-1",
            "https://example.com/a",
            "Example",
            "article",
            "Example Canonical",
        )
    ]
    session = _FakeSession(rows)

    def fake_db_manager():
        return _FakeDBManager(session)

    class FakeExtractor:
        def __init__(self):
            self.rate_limited = set()

        def _check_rate_limit(self, domain):
            return domain in self.rate_limited

        def extract_content(self, *_a, **_kw):
            return {
                "title": "Title",
                "content": "Body text",
                "author": "Alice",
                "metadata": {
                    "extraction_methods": {"title": "newspaper4k"}
                },
            }

        def get_driver_stats(self):
            return {
                "has_persistent_driver": False,
                "driver_reuse_count": 0,
                "driver_creation_count": 0,
            }

    class FakeByline:
        def clean_byline(self, *_a, **_kw):
            return {"authors": ["Alice"], "wire_services": []}

    class FakeDetector:
        def detect(self, **_kw):
            return None

    telemetry_calls = []

    class FakeTelemetry:
        def record_extraction(self, metrics):
            telemetry_calls.append(metrics)

    class FakeMetrics:
        def __init__(self, *_a, **_kw):
            self.error_message = None
            self.error_type = None

        def set_content_type_detection(self, *_a, **_kw):
            return None

        def finalize(self, *_a, **_kw):
            return None

    monkeypatch.setattr(extraction, "DatabaseManager", fake_db_manager)
    monkeypatch.setattr(extraction, "BylineCleaner", FakeByline)
    monkeypatch.setattr(extraction, "ContentExtractor", FakeExtractor)
    monkeypatch.setattr(
        extraction,
        "ComprehensiveExtractionTelemetry",
        FakeTelemetry,
    )
    monkeypatch.setattr(extraction, "ExtractionMetrics", FakeMetrics)
    monkeypatch.setattr(
        extraction,
        "calculate_content_hash",
        lambda *_a, **_kw: "hash",
    )
    monkeypatch.setattr(
        extraction,
        "_get_content_type_detector",
        lambda: FakeDetector(),
    )

    domains_for_cleaning = defaultdict(list)
    host_403_tracker = {}
    extractor = FakeExtractor()
    telemetry = FakeTelemetry()

    result = extraction._process_batch(
        Namespace(limit=1, source=None),
        extractor,
        FakeByline(),
        telemetry,
        1,
        1,
        host_403_tracker,
        domains_for_cleaning,
    )

    assert result["processed"] == 1
    assert domains_for_cleaning["example.com"]
    assert session.commit_calls >= 1
    assert telemetry_calls


def test_process_batch_rate_limited(monkeypatch):
    rows = [
        ("cand-1", "https://blocked.com/a", "Example", "article", None)
    ]
    session = _FakeSession(rows)

    def fake_db_manager():
        return _FakeDBManager(session)

    class BlockingExtractor:
        def _check_rate_limit(self, domain):
            return domain == "blocked.com"

        def get_driver_stats(self):
            return {
                "has_persistent_driver": False,
                "driver_reuse_count": 0,
                "driver_creation_count": 0,
            }

    monkeypatch.setattr(extraction, "DatabaseManager", fake_db_manager)

    result = extraction._process_batch(
        Namespace(limit=1, source=None),
        BlockingExtractor(),
        object(),
        object(),
        1,
        1,
        {},
        defaultdict(list),
    )

    assert result["processed"] == 0
    assert result["skipped_domains"] == 1


def test_run_post_extraction_cleaning_updates_status(monkeypatch):
    cleaner_calls = []

    class FakeCleaner:
        def __init__(self, *_, **__):
            pass

        def analyze_domain(self, domain):
            cleaner_calls.append(("analyze", domain))

        def process_single_article(self, *, text, domain, article_id):
            cleaner_calls.append(("clean", domain, article_id, text))
            return text + "!", {"chars_removed": 1}

    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            if not self._rows:
                return None
            return self._rows.pop(0)

    class FakeSession:
        def __init__(self):
            self.updates = []
            self.closed = False

        def execute(self, query, params=None):
            if "SELECT content" in str(query):
                return FakeQuery([["content", "extracted"]])
            self.updates.append((query, params))
            return _FakeResult([])

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    class FakeDB:
        def __init__(self):
            self.session = FakeSession()

    monkeypatch.setattr(
        extraction,
        "BalancedBoundaryContentCleaner",
        FakeCleaner,
    )
    monkeypatch.setattr(extraction, "DatabaseManager", lambda: FakeDB())
    monkeypatch.setattr(
        extraction,
        "calculate_content_hash",
        lambda *_a, **_kw: "hash",
    )

    def fake_commit_with_retry(session):
        if hasattr(session, "commit_calls"):
            session.commit_calls += 1

    monkeypatch.setattr(
        extraction,
        "_commit_with_retry",
        fake_commit_with_retry,
    )

    def fake_entity_extraction(ids):
        cleaner_calls.append(("entities", sorted(ids)))

    monkeypatch.setattr(
        extraction,
        "_run_article_entity_extraction",
        fake_entity_extraction,
    )

    domains = {"example.com": ["article-1"]}
    extraction._run_post_extraction_cleaning(domains)

    assert any(call[0] == "clean" for call in cleaner_calls)
    assert any(call[0] == "entities" for call in cleaner_calls)


def test_run_article_entity_extraction_handles_skip(monkeypatch):
    class FakeExtractor:
        extractor_version = "v1"

        def extract(self, *_a, **_kw):
            return []

    class FakeArticle:
        def __init__(self):
            self.id = "a1"
            self.status = "wire"
            self.text = ""
            self.content = ""
            link_cls = type("C", (), {"source_id": None, "dataset_id": None})
            self.candidate_link = link_cls()
            self.text_hash = "hash"

    class FakeQuery:
        def __init__(self, articles):
            self._articles = articles

        def join(self, *_a, **_kw):
            return self

        def filter(self, *_a, **_kw):
            return self

        def all(self):
            return self._articles

    class FakeSession:
        def __init__(self):
            self.queries = []

        def query(self, *_a, **_kw):
            return FakeQuery([FakeArticle()])

        def rollback(self):
            pass

        def close(self):
            pass

    class FakeDB:
        def __init__(self):
            self.session = FakeSession()

    monkeypatch.setattr(
        extraction,
        "_get_entity_extractor",
        lambda: FakeExtractor(),
    )
    monkeypatch.setattr(extraction, "DatabaseManager", lambda: FakeDB())
    monkeypatch.setattr(extraction, "get_gazetteer_rows", lambda *a, **k: [])

    def passthrough_matches(*_args, entities, **_kwargs):
        return entities

    monkeypatch.setattr(
        extraction,
        "attach_gazetteer_matches",
        passthrough_matches,
    )
    monkeypatch.setattr(
        extraction,
        "save_article_entities",
        lambda *_a, **_kw: None,
    )

    extraction._run_article_entity_extraction(["a1", "a2"])

    # Wire articles are skipped, so no exception occurs
