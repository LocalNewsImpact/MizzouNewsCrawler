"""Services for applying machine learning classifiers to articles."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

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
    ) -> list[list[Prediction]]: ...


@dataclass
class ClassificationStats:
    """Statistics collected during a classification run."""

    processed: int = 0
    labeled: int = 0
    skipped: int = 0
    errors: int = 0
    proposed_labels: list[dict[str, object]] = field(default_factory=list)


class ArticleClassificationService:
    """Apply text classification models to articles in the database."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.logger = logging.getLogger(self.__class__.__name__)

    def _select_articles(
        self,
        statuses: Sequence[str] | None,
        label_version: str,
        limit: int | None,
        include_existing: bool,
        excluded_statuses: Sequence[str] | None = None,
    ) -> list[Article]:
        stmt = select(Article)

        if statuses:
            stmt = stmt.where(Article.status.in_(list(statuses)))

        if excluded_statuses:
            stmt = stmt.where(Article.status.notin_(list(excluded_statuses)))

        if not include_existing:
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
        
        # Add row-level locking for parallel processing without race conditions
        # SKIP LOCKED allows multiple workers to process different rows simultaneously
        stmt = stmt.with_for_update(skip_locked=True)

        return list(self.session.scalars(stmt))

    def _prepare_text(self, article: Article) -> str | None:
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
        model_version: str | None = None,
        model_path: str | None = None,
        statuses: Sequence[str] | None = ("cleaned", "local"),
        limit: int | None = None,
        batch_size: int = 16,
        top_k: int = 2,
        dry_run: bool = False,
        include_existing: bool = False,
    ) -> ClassificationStats:
        """Classify eligible articles and persist results."""

        excluded_statuses = {
            "opinion",
            "opinions",
            "obituary",
            "obits",
            "wire",
        }
        if statuses is None:
            effective_statuses: list[str] | None = None
        else:
            effective_statuses = [
                status for status in statuses if status not in excluded_statuses
            ]
            if not effective_statuses:
                self.logger.info(
                    "No eligible statuses after excluding %s content",
                    ", ".join(sorted(excluded_statuses)),
                )
                return ClassificationStats()

        articles = self._select_articles(
            effective_statuses,
            label_version,
            limit,
            include_existing,
            list(excluded_statuses),
        )
        stats = ClassificationStats(processed=len(articles))

        if not articles:
            return stats

        effective_model_version = model_version or classifier.model_version or "unknown"
        effective_model_path = model_path or getattr(
            classifier, "model_identifier", None
        )
        if effective_model_path is not None:
            effective_model_path = str(effective_model_path)

        for batch in _batch_iter(articles, batch_size):
            texts: list[str] = []
            article_refs: list[Article] = []

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

            for article, predictions in zip(
                article_refs, predictions_batch, strict=False
            ):
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
                    article_id_value = getattr(article, "id", None)
                    stats.proposed_labels.append(
                        {
                            "article_id": (
                                str(article_id_value)
                                if article_id_value is not None
                                else ""
                            ),
                            "url": getattr(article, "url", ""),
                            "primary": primary.label,
                            "alternate": (alternate.label if alternate else ""),
                            "top_k": [pred.as_dict() for pred in predictions],
                        }
                    )
                    self.logger.info(
                        "[dry-run] %s -> %s (alt=%s)",
                        article_id_value or "<unknown>",
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
        yield items[start : start + batch_size]
