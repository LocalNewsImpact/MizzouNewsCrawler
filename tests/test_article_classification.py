"""Tests for article classification persistence and service."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.ml.article_classifier import Prediction
from src.models import Article, ArticleLabel
from src.models.database import DatabaseManager, save_article_classification
from src.services.classification_service import ArticleClassificationService


@pytest.fixture
def db_session():
    db = DatabaseManager("sqlite:///:memory:")
    try:
        yield db.session
    finally:
        db.close()


def _create_article(session, **kwargs):
    defaults = {
        "id": kwargs.get("id", "article-1"),
        "candidate_link_id": kwargs.get("candidate_link_id", "link-1"),
        "url": kwargs.get("url", "https://example.com/1"),
        "status": kwargs.get("status", "cleaned"),
        "content": kwargs.get("content", "Local news story"),
        "text": kwargs.get("text", "Local news story"),
        "title": kwargs.get("title", "Sample Article"),
        "created_at": datetime.utcnow(),
    }
    article = Article(**defaults)
    session.add(article)
    session.commit()
    return article


def test_save_article_classification_persists_labels(db_session):
    article = _create_article(db_session)

    primary = Prediction(label="local", score=0.9)
    alternate = {"label": "wire", "score": 0.1}

    save_article_classification(
        db_session,
        article_id=str(article.id),
        label_version="v1",
        model_version="model-1",
        primary_prediction=primary,
        alternate_prediction=alternate,
        model_path="models/production",
        metadata={"source": "test"},
    )

    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    saved_label = (
        db_session.query(ArticleLabel)
        .filter_by(article_id=article.id, label_version="v1")
        .one()
    )

    assert saved_label.primary_label == "local"
    assert pytest.approx(saved_label.primary_label_confidence, rel=1e-6) == 0.9
    assert saved_label.alternate_label == "wire"
    assert refreshed_article.primary_label == "local"
    assert refreshed_article.label_model_version == "model-1"
    assert refreshed_article.label_version == "v1"


def test_article_classification_service_applies_model(db_session):
    class StubClassifier:
        model_version: str | None = "stub-model"
        model_identifier: str | None = "stub-path"

        def predict_batch(self, texts, *, top_k=2):
            return [
                [
                    Prediction(label="Local", score=0.8),
                    Prediction(label="Wire", score=0.2),
                ]
                for _ in texts
            ]

    article_with_text = _create_article(db_session, id="article-a")
    _create_article(db_session, id="article-b", content="", text="", title="")

    service = ArticleClassificationService(db_session)
    classifier = StubClassifier()

    stats = service.apply_classification(
        classifier,
        label_version="test-version",
        model_version=None,
        model_path="stub-path",
        statuses=["cleaned"],
        limit=None,
        batch_size=4,
        top_k=2,
        dry_run=False,
    )

    assert stats.processed == 2
    assert stats.labeled == 1
    assert stats.skipped >= 1

    saved_label = (
        db_session.query(ArticleLabel)
        .filter_by(
            article_id=article_with_text.id,
            label_version="test-version",
        )
        .one()
    )
    assert saved_label.primary_label == "Local"
    assert saved_label.alternate_label == "Wire"


def test_classification_skips_opinion_and_obituary_statuses(db_session):
    class StubClassifier:
        model_version: str | None = "stub-model"
        model_identifier: str | None = "stub-path"

        def predict_batch(self, texts, *, top_k=2):
            return [[Prediction(label="Local", score=0.9)] for _ in texts]

    # Eligible cleaned article
    eligible = _create_article(
        db_session,
        id="cleaned-article",
        status="cleaned",
        content="Content",
    )
    # Should be skipped due to status
    _create_article(
        db_session,
        id="opinion-article",
        status="opinion",
        content="Opinion piece",
    )
    _create_article(
        db_session,
        id="obituary-article",
        status="obituary",
        content="Obituary piece",
    )

    service = ArticleClassificationService(db_session)
    classifier = StubClassifier()

    stats = service.apply_classification(
        classifier,
        label_version="skip-test",
        statuses=["cleaned", "opinion", "obituary"],
    )

    assert stats.processed == 1
    assert stats.labeled == 1

    saved_label = (
        db_session.query(ArticleLabel)
        .filter_by(article_id=eligible.id, label_version="skip-test")
        .one()
    )
    assert saved_label.primary_label == "Local"
