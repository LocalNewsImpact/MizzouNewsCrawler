"""Services for applying machine learning classifiers to articles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ml.article_classifier import Prediction
from src.models import Article, ArticleLabel
from src.models.database import save_article_classification

logger = logging.getLogger(__name__)


class BatchClassifier(Protocol):
    """Protocol describing the classifier interface used by the service."""

    model_version: str | None
    model_identifier: str | None

    def predict_batch(
        self,
        texts: Sequence[str],
        *,
        top_k: int = 2,
    ) -> List[List[Prediction]]:
        ...


@dataclass
class ClassificationStats:
    """Statistics collected during a classification run."""

    processed: int = 0
    labeled: int = 0
    skipped: int = 0
    errors: int = 0


class ArticleClassificationService:
    """Apply text classification models to articles in the database."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.logger = logging.getLogger(self.__class__.__name__)

    def _select_articles(
        self,
        statuses: Sequence[str],
        label_version: str,
        limit: Optional[int],
    ) -> List[Article]:
        stmt = select(Article).where(Article.status.in_(list(statuses)))

        label_exists = (
            select(ArticleLabel.id)
            .where(
                ArticleLabel.article_id == Article.id,
                ArticleLabel.label_version == label_version,
            )
            .exists()
        )
        stmt = stmt.where(~label_exists)
        stmt = stmt.order_by(Article.created_at.desc())
        if limit:
            stmt = stmt.limit(limit)

        return list(self.session.scalars(stmt))

    def _prepare_text(self, article: Article) -> Optional[str]:
        for field_name in ("content", "text", "title"):
            value = getattr(article, field_name, None)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def apply_classification(
        self,
        classifier: BatchClassifier,
        *,
        label_version: str,
        model_version: Optional[str] = None,
        model_path: Optional[str] = None,
        statuses: Sequence[str] = ("cleaned", "local"),
        limit: Optional[int] = None,
        batch_size: int = 16,
        top_k: int = 2,
        dry_run: bool = False,
    ) -> ClassificationStats:
        """Classify eligible articles and persist results."""

        articles = self._select_articles(statuses, label_version, limit)
        stats = ClassificationStats(processed=len(articles))

        if not articles:
            return stats

        effective_model_version = (
            model_version or classifier.model_version or "unknown"
        )
        effective_model_path = (
            model_path or getattr(classifier, "model_identifier", None)
        )
        if effective_model_path is not None:
            effective_model_path = str(effective_model_path)

        for batch in _batch_iter(articles, batch_size):
            texts: List[str] = []
            article_refs: List[Article] = []

            for article in batch:
                text = self._prepare_text(article)
                if not text:
                    stats.skipped += 1
                    self.logger.debug(
                        "Skipping article %s due to empty content",
                        getattr(article, "id", "<unknown>"),
                    )
                    continue
                texts.append(text)
                article_refs.append(article)

            if not texts:
                continue

            try:
                predictions_batch = classifier.predict_batch(
                    texts,
                    top_k=top_k,
                )
            except Exception as exc:  # pylint: disable=broad-except
                stats.errors += len(texts)
                self.logger.exception("Classifier failed on batch: %s", exc)
                continue

            for article, predictions in zip(article_refs, predictions_batch):
                if not predictions:
                    stats.skipped += 1
                    self.logger.debug(
                        "Classifier returned no predictions for article %s",
                        getattr(article, "id", "<unknown>"),
                    )
                    continue

                primary = predictions[0]
                alternate = predictions[1] if len(predictions) > 1 else None

                metadata = {
                    "top_k": [pred.as_dict() for pred in predictions],
                    "applied_at": datetime.utcnow().isoformat(),
                }

                if dry_run:
                    stats.labeled += 1
                    self.logger.info(
                        "[dry-run] %s -> %s (alt=%s)",
                        getattr(article, "id", "<unknown>"),
                        primary.label,
                        alternate.label if alternate else None,
                    )
                    continue

                article_id_value = getattr(article, "id", None)
                if not article_id_value:
                    stats.errors += 1
                    self.logger.error(
                        "Article missing ID; cannot record classification"
                    )
                    continue

                save_article_classification(
                    self.session,
                    article_id=str(article_id_value),
                    label_version=label_version,
                    model_version=effective_model_version,
                    primary_prediction=primary,
                    alternate_prediction=alternate,
                    model_path=effective_model_path,
                    metadata=metadata,
                )
                stats.labeled += 1

        return stats


def _batch_iter(
    items: Sequence[Article],
    batch_size: int,
) -> Iterable[Sequence[Article]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]
