from __future__ import annotations

import logging
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scripts.backfill import backfill_article_entities as backfill_module
from src.models import Article, ArticleEntity, Base, CandidateLink


@pytest.fixture
def db_session_factory(monkeypatch):
    """Provide in-memory DB session factory and patch DatabaseManager."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    class FakeDatabaseManager:  # pragma: no cover - simple wiring
        def __init__(self):
            self.engine = engine
            self.session = Session()

        def close(self):
            self.session.close()

    monkeypatch.setattr(
        backfill_module,
        "DatabaseManager",
        FakeDatabaseManager,
    )
    yield Session
    engine.dispose()


@pytest.fixture
def stub_extractor(monkeypatch):
    class StubExtractor:
        def __init__(self, model_name: str = "en_core_web_sm") -> None:
            self.model_name = model_name
            self.extractor_version = f"stub-{model_name}"

    monkeypatch.setattr(
        backfill_module,
        "ArticleEntityExtractor",
        StubExtractor,
    )
    return StubExtractor


def test_run_backfill_dry_run_skips_processing(
    db_session_factory,
    stub_extractor,
    caplog,
    monkeypatch,
):
    Session = db_session_factory

    session = Session()
    candidate = CandidateLink(
        id="cl-dry-run",
        url="https://example.com/article",
        source="Example News",
        status="article",
    )
    article = Article(
        id="article-dry-run",
        candidate_link_id=candidate.id,
        status="extracted",
        extracted_at=datetime.utcnow(),
        content="Body text",
        text="Body text",
        text_hash="hash-dry",
    )
    session.add_all([candidate, article])
    session.commit()
    session.close()

    batches: list[list[str]] = []

    def fake_process(ids):
        batches.append(list(ids))

    monkeypatch.setattr(backfill_module, "_process_batch", fake_process)
    monkeypatch.setattr(
        backfill_module.extraction_commands,
        "_ENTITY_EXTRACTOR",
        None,
    )

    parser = backfill_module.build_parser()
    args = parser.parse_args(["--dry-run", "--source", "Example News"])

    with caplog.at_level(logging.INFO):
        backfill_module.run_backfill(args)

    assert batches == []
    assert "Dry run: would process 1 article(s)" in caplog.text

    check_session = Session()
    assert check_session.query(ArticleEntity).count() == 0
    check_session.close()


def test_run_backfill_processes_missing_entities(
    db_session_factory,
    stub_extractor,
    caplog,
    monkeypatch,
):
    Session = db_session_factory

    session = Session()
    candidate1 = CandidateLink(
        id="cl-needs",
        url="https://example.com/needs",
        source="Example News",
        status="article",
    )
    candidate2 = CandidateLink(
        id="cl-has",
        url="https://example.com/has",
        source="Example News",
        status="article",
    )
    article_needs = Article(
        id="article-needs",
        candidate_link_id=candidate1.id,
        status="extracted",
        extracted_at=datetime.utcnow(),
        content="Alpha",
        text="Alpha",
        text_hash="hash-alpha",
    )
    article_has = Article(
        id="article-has",
        candidate_link_id=candidate2.id,
        status="extracted",
        extracted_at=datetime.utcnow(),
        content="Beta",
        text="Beta",
        text_hash="hash-beta",
    )
    existing_entity = ArticleEntity(
        article_id=article_has.id,
        article_text_hash="hash-beta",
        entity_text="Beta Org",
        entity_norm="beta org",
        entity_label="ORG",
        osm_category="business",
        extractor_version="stub-en_core_web_sm",
    )
    session.add_all(
        [
            candidate1,
            candidate2,
            article_needs,
            article_has,
            existing_entity,
        ]
    )
    session.commit()
    session.close()

    captured_batches: list[tuple[str, ...]] = []

    def fake_run(article_ids):
        captured_batches.append(tuple(sorted(article_ids)))

    monkeypatch.setattr(
        backfill_module.extraction_commands,
        "_run_article_entity_extraction",
        fake_run,
    )
    monkeypatch.setattr(
        backfill_module.extraction_commands,
        "_ENTITY_EXTRACTOR",
        None,
    )

    parser = backfill_module.build_parser()
    args = parser.parse_args(["--source", "Example News"])

    with caplog.at_level(logging.INFO):
        backfill_module.run_backfill(args)

    assert captured_batches == [("article-needs",)]
    assert "Entity backfill complete; processed 1 article(s)." in caplog.text

    check_session = Session()
    assert check_session.query(ArticleEntity).count() == 1
    check_session.close()
