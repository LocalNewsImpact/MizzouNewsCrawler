from __future__ import annotations

import types
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.ml.article_classifier import Prediction

# Article imported previously for casting; not required after test refactor
from src.services.classification_service import (
    ArticleClassificationService,
    ClassificationStats,
    _batch_iter,
)


class DummyClassifier:
    model_version: str | None
    model_identifier: str | None

    def __init__(
        self,
        responses,
        *,
        model_version: str | None = "v1",
        model_identifier: str | None = "model.pt",
        error: Exception | None = None,
    ) -> None:
        self._responses = responses
        self.model_version = model_version
        self.model_identifier = model_identifier
        self._error = error
        self.calls: list[tuple[list[str], int]] = []

    def predict_batch(self, texts, *, top_k: int = 2):  # noqa: D401
        self.calls.append((list(texts), top_k))
        if self._error is not None:
            raise self._error
        return self._responses


def _make_article(**overrides):
    defaults = {
        "id": "article-1",
        "content": "Important civic update",
        "text": None,
        "title": "",
        "url": "https://example.com/story",
        "status": "cleaned",
        "created_at": datetime(2024, 1, 1),
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _make_service() -> ArticleClassificationService:
    session = MagicMock(spec=Session)
    session.bind = None  # avoid hitting dialect detection in tests
    session.scalars = MagicMock(return_value=iter(()))
    return ArticleClassificationService(session=session)


def test_prepare_text_prefers_first_non_empty_field():
    service = _make_service()
    article = _make_article(
        content="\n\n",
        text="  candidate text  ",
        title="Headline",
    )
    assert service._prepare_text(article) == (  # type: ignore[arg-type]
        "  candidate text  "
    )

    empty_article = _make_article(content="", text="   ", title="  ")
    assert service._prepare_text(empty_article) is None  # type: ignore[arg-type]


def test_apply_classification_returns_empty_stats_when_statuses_filtered():
    service = _make_service()
    classifier = DummyClassifier([])

    stats = service.apply_classification(
        classifier,
        label_version="v1",
        statuses=("wire", "opinion"),
    )

    assert stats == ClassificationStats()
    assert classifier.calls == []


def test_apply_classification_dry_run_collects_proposed_labels(monkeypatch):
    service = _make_service()
    articles = [
        _make_article(
            id=321,
            content="Body content",
            url="https://example.com/a",
        )
    ]

    captured = {}
    call_count = 0

    def fake_select(
        statuses,
        label_version,
        limit,
        include_existing,
        excluded,
        excluded_ids=None,
    ):
        nonlocal call_count
        if call_count:
            return []
        call_count += 1
        captured["statuses"] = statuses
        captured["label_version"] = label_version
        assert include_existing is False
        assert isinstance(excluded, list)
        return list(articles)

    monkeypatch.setattr(service, "_select_articles", fake_select)
    monkeypatch.setattr(
        "src.services.classification_service.save_article_classification",
        lambda *args, **kwargs: pytest.fail("save should not be called in dry-run"),
    )

    predictions = [
        [
            Prediction(label="Local", score=0.9),
            Prediction(label="Sports", score=0.1),
        ]
    ]
    classifier = DummyClassifier(
        predictions,
        model_version="2025.09",
        model_identifier="model.bin",
    )

    stats = service.apply_classification(
        classifier,
        label_version="v2",
        dry_run=True,
        top_k=3,
    )

    assert captured["statuses"] == ["cleaned", "local"]
    assert captured["label_version"] == "v2"
    assert len(classifier.calls) == 1

    assert stats.processed == 1
    assert stats.labeled == 1
    assert stats.skipped == 0
    assert not stats.errors
    assert stats.proposed_labels[0]["primary"] == "Local"
    assert stats.proposed_labels[0]["alternate"] == "Sports"
    assert stats.proposed_labels[0]["top_k"] == [
        pred.as_dict() for pred in predictions[0]
    ]


def test_apply_classification_persists_predictions(monkeypatch):
    service = _make_service()
    articles = [_make_article(id=999, content="Body", url="https://example.com/real")]
    call_count = 0

    def fake_select(*_args, **_kwargs):
        nonlocal call_count
        if call_count:
            return []
        call_count += 1
        return list(articles)

    monkeypatch.setattr(service, "_select_articles", fake_select)

    saved_calls = []

    def fake_save(session, **kwargs):
        saved_calls.append({"session": session, **kwargs})

    monkeypatch.setattr(
        "src.services.classification_service.save_article_classification",
        fake_save,
    )

    predictions = [
        [
            Prediction(label="Civic", score=0.8),
            Prediction(label="Economy", score=0.2),
        ]
    ]
    classifier = DummyClassifier(
        predictions,
        model_version="2025.10",
        model_identifier="model.pt",
    )

    stats = service.apply_classification(
        classifier,
        label_version="impact-v1",
        batch_size=2,
        dry_run=False,
        include_existing=False,
    )

    assert stats.processed == 1
    assert stats.labeled == 1
    assert stats.skipped == 0
    assert stats.errors == 0
    assert stats.proposed_labels == []

    assert len(saved_calls) == 1
    saved = saved_calls[0]
    assert saved["session"] is service.session
    assert saved["article_id"] == "999"
    assert saved["label_version"] == "impact-v1"
    assert saved["model_version"] == "2025.10"
    assert saved["primary_prediction"].label == "Civic"
    assert saved["alternate_prediction"].label == "Economy"
    assert "metadata" in saved
    assert saved["metadata"]["top_k"] == [pred.as_dict() for pred in predictions[0]]


def test_apply_classification_records_error_when_missing_id(monkeypatch):
    service = _make_service()
    articles = [
        _make_article(
            id=None,
            content="Has text",
            url="https://example.com/missing",
        )
    ]
    call_count = 0

    def fake_select(*_args, **_kwargs):
        nonlocal call_count
        if call_count:
            return []
        call_count += 1
        return list(articles)

    monkeypatch.setattr(service, "_select_articles", fake_select)

    saved_calls = []
    monkeypatch.setattr(
        "src.services.classification_service.save_article_classification",
        lambda *args, **kwargs: saved_calls.append(kwargs),
    )

    predictions = [[Prediction(label="Local", score=1.0)]]
    classifier = DummyClassifier(predictions)

    stats = service.apply_classification(
        classifier,
        label_version="v1",
    )

    assert stats.processed == 1
    assert stats.labeled == 0
    assert stats.errors == 1
    assert saved_calls == []


def test_apply_classification_skips_articles_with_no_text(monkeypatch):
    service = _make_service()
    article = _make_article(content="", text="  ", title=" ")
    call_count = 0

    def fake_select(*_args, **_kwargs):
        nonlocal call_count
        if call_count:
            return []
        call_count += 1
        return [article]

    monkeypatch.setattr(service, "_select_articles", fake_select)

    classifier = DummyClassifier(
        [],
        error=AssertionError("classifier should not run"),
    )

    stats = service.apply_classification(
        classifier,
        label_version="v1",
    )

    assert stats.processed == 1
    assert stats.skipped == 1
    assert stats.labeled == 0
    assert stats.errors == 0
    assert classifier.calls == []


def test_apply_classification_handles_classifier_exception(monkeypatch):
    service = _make_service()
    articles = [
        _make_article(id="1", content="First", url="https://example.com/1"),
        _make_article(id="2", content="Second", url="https://example.com/2"),
    ]
    call_count = 0

    def fake_select(*_args, **_kwargs):
        nonlocal call_count
        if call_count:
            return []
        call_count += 1
        return list(articles)

    monkeypatch.setattr(service, "_select_articles", fake_select)

    classifier = DummyClassifier([], error=RuntimeError("boom"))

    stats = service.apply_classification(
        classifier,
        label_version="v1",
    )

    assert stats.processed == 2
    assert stats.errors == 2
    assert stats.labeled == 0


def test_apply_classification_skips_empty_predictions(monkeypatch):
    service = _make_service()
    articles = [_make_article(id="1", content="Text")]
    call_count = 0

    def fake_select(*_args, **_kwargs):
        nonlocal call_count
        if call_count:
            return []
        call_count += 1
        return list(articles)

    monkeypatch.setattr(service, "_select_articles", fake_select)

    classifier = DummyClassifier([[]])

    stats = service.apply_classification(
        classifier,
        label_version="v1",
    )

    assert stats.processed == 1
    assert stats.labeled == 0
    assert stats.skipped == 1
    assert stats.errors == 0
    assert len(classifier.calls) == 1


def test_apply_classification_handles_none_statuses(monkeypatch):
    service = _make_service()
    captured: dict[str, Any] = {}

    def fake_select(
        statuses,
        label_version,
        limit,
        include_existing,
        excluded,
        excluded_ids=None,
    ):
        captured.update(
            {
                "statuses": statuses,
                "label_version": label_version,
                "limit": limit,
                "include_existing": include_existing,
                "excluded": tuple(sorted(excluded)),
                "excluded_ids": tuple(sorted(excluded_ids or [])),
            }
        )
        return []

    monkeypatch.setattr(service, "_select_articles", fake_select)

    classifier = DummyClassifier([])
    stats = service.apply_classification(
        classifier,
        label_version="beta",
        statuses=None,
        limit=7,
        include_existing=True,
    )

    assert stats.processed == 0
    assert stats.labeled == 0
    assert stats.skipped == 0
    assert stats.errors == 0
    assert stats.proposed_labels == []

    assert captured["statuses"] is None
    assert captured["label_version"] == "beta"
    assert captured["limit"] == 7
    assert captured["include_existing"] is True

    excluded = captured["excluded"]
    assert isinstance(excluded, tuple)
    assert "wire" in excluded


def test_batch_iter_requires_positive_size():
    articles = [_make_article(id="a")]  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        list(_batch_iter(articles, 0))  # type: ignore[arg-type]


def test_batch_iter_yields_even_chunks():
    items = [
        _make_article(id="1"),
        _make_article(id="2"),
        _make_article(id="3"),
        _make_article(id="4"),
        _make_article(id="5"),
    ]  # type: ignore[arg-type]
    chunks = list(_batch_iter(items, 2))  # type: ignore[arg-type]
    assert chunks == [items[0:2], items[2:4], items[4:5]]


@pytest.mark.postgres
@pytest.mark.integration
def test_select_articles_applies_limit_clause():
    service = _make_service()
    session_mock = service.session  # type: ignore[assignment]
    # session_mock is a MagicMock in tests; mypy cannot infer attributes here
    session_mock.scalars.return_value = iter(())  # type: ignore[attr-defined]

    results = service._select_articles(
        statuses=("cleaned",),
        label_version="v1",
        limit=5,
        include_existing=True,
    )

    assert results == []
    stmt = session_mock.scalars.call_args[0][0]  # type: ignore[union-attr]
    assert getattr(stmt, "_limit_clause", None) is not None
    assert getattr(stmt._limit_clause, "value", None) == 5
