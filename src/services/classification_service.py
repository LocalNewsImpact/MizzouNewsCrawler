"""Services for applying machine learning classifiers to articles."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.ml.article_classifier import Prediction
from src.models import Article, ArticleLabel, CandidateLink
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

    @staticmethod
    def _articles_owed_a_classification(session):
        """The articles `pipeline_rework` says still need classifying.

        Read from the database, not from a file handed between pods: a
        file and the database disagree the moment a run dies halfway. An
        empty result means nothing to do -- never "no filter".
        """
        rows = session.execute(
            text(
                "SELECT record_id FROM pipeline_rework "
                "WHERE record_type = 'article' AND stage = 'classify' "
                "AND done_at IS NULL ORDER BY requested_at"
            )
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _settle_rework(session, record_ids, outcome):
        """Close this stage's rework rows for the articles it classified,
        and queue the same articles for enrichment.

        Each stage hands off to the next: the reconciler writes only the
        row for the stage a record re-enters at, and a stage that
        finishes queues the one after it. Enrichment selects `labeled`,
        which is what classification just wrote, so the row is written
        for the article as it now is. A duplicate request is the same
        request (partial unique index; `ON CONFLICT DO NOTHING`).
        """
        if not record_ids:
            return
        ids = [str(i) for i in record_ids]
        session.execute(
            text(
                "UPDATE pipeline_rework SET done_at = now(), outcome = :outcome "
                "WHERE record_type = 'article' AND stage = 'classify' "
                "AND record_id = ANY(:ids) AND done_at IS NULL"
            ),
            {"outcome": outcome, "ids": ids},
        )
        session.execute(
            text(
                "INSERT INTO pipeline_rework "
                "(record_type, record_id, stage, reason, requested_by) "
                "SELECT 'article', r.record_id, 'enrich', "
                "'classified for rework: ' || COALESCE(r.reason, ''), 'housekeeping' "
                "FROM pipeline_rework r "
                "WHERE r.record_type = 'article' AND r.stage = 'classify' "
                "AND r.record_id = ANY(:ids) AND r.outcome = :outcome "
                "ON CONFLICT DO NOTHING"
            ),
            {"outcome": outcome, "ids": ids},
        )

    def _select_articles(
        self,
        statuses: Sequence[str] | None,
        label_version: str,
        limit: int | None,
        include_existing: bool,
        excluded_statuses: Sequence[str] | None = None,
        excluded_article_ids: Sequence[str] | None = None,
        dataset_id: str | None = None,
        only_article_ids: Sequence[str] | None = None,
    ) -> list[Article]:
        stmt = select(Article)

        # ONLY THESE ARTICLES, WHEN NAMED.
        #
        # Every other argument here narrows a population; this replaces
        # it. A caller that knows which records it is for -- housekeeping,
        # carrying the handful a review decision rewound -- must be able
        # to say so, or it classifies whatever else shares a status. An
        # empty list means "none", not "no filter": those are opposite
        # instructions and conflating them is how a targeted run becomes
        # a sweep.
        if only_article_ids is not None:
            if not only_article_ids:
                return []
            stmt = stmt.where(Article.id.in_(list(only_article_ids)))

        if statuses:
            stmt = stmt.where(Article.status.in_(list(statuses)))

        if excluded_statuses:
            stmt = stmt.where(Article.status.notin_(list(excluded_statuses)))

        # Articles carry no dataset of their own; the dataset is a property of
        # the candidate link they were discovered through. EXISTS rather than a
        # join so the FOR UPDATE SKIP LOCKED below keeps locking articles only.
        if dataset_id:
            in_dataset = (
                select(CandidateLink.id)
                .where(
                    CandidateLink.id == Article.candidate_link_id,
                    CandidateLink.dataset_id == dataset_id,
                )
                .exists()
            )
            stmt = stmt.where(in_dataset)

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

        # Add row-level locking for parallel processing (PostgreSQL only)
        # SKIP LOCKED allows multiple workers to process different rows simultaneously
        # SQLite doesn't support FOR UPDATE, so skip it for e2e/unit tests
        try:
            dialect_name = self.session.bind.dialect.name if self.session.bind else None
        except AttributeError:
            # Mock session in tests
            dialect_name = None

        if excluded_article_ids:
            stmt = stmt.where(Article.id.notin_(list(excluded_article_ids)))

        if dialect_name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        return list(self.session.scalars(stmt))

    # The body the classifier sees, in order of preference.
    #
    # `text` is the cleaned body, `content` the raw capture. Classifying the raw
    # capture means classifying whatever the page happened to carry — navigation
    # menus, paywall prompts, cookie notices. 3% of stored articles are mostly
    # nav chrome, and for those the CIN label was derived from a list of section
    # names rather than from any reporting.
    #
    # This used to read `content` first and return it alone. That was harmless
    # while extraction wrote the same string to both columns, and became wrong
    # the moment they diverged. `content` stays as the fallback for rows
    # extracted before the split, where the raw capture is the only body there
    # is.
    _BODY_FIELD_PREFERENCE = ("text", "content")

    def _prepare_text(self, article: Article) -> str | None:
        """Headline plus cleaned body — the two together, not the first of them.

        A headline is a dense statement of what a story is about, which is
        exactly the judgement the CIN classifier makes, so it is prepended to
        the body rather than used only as a last resort. Either part may be
        missing; whatever is present is classified.
        """
        parts: list[str] = []

        title = getattr(article, "title", None)
        if isinstance(title, str) and title.strip():
            parts.append(title.strip())

        for field_name in self._BODY_FIELD_PREFERENCE:
            value = getattr(article, field_name, None)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
                break

        return "\n\n".join(parts) if parts else None

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
        dataset_id: str | None = None,
        rework: bool = False,
    ) -> ClassificationStats:
        """Classify eligible articles and persist results.

        `rework=True` classifies ONLY the articles `pipeline_rework` says
        owe it -- the records a review decision rewound -- and closes
        those rows when done. Without it every article at an eligible
        status is taken, which is the pipeline's job and not
        housekeeping's: 450 sat at `cleaned` the night 14 of them were
        put there by a decision.

        Parallel Processing with Row-Level Locking:
        ------------------------------------------
        Uses PostgreSQL FOR UPDATE SKIP LOCKED for safe parallel processing:

        1. Select batch_size articles with row locks
        2. Process each article with save(autocommit=False)
        3. Commit entire batch together, releasing all locks
        4. Other workers skip locked articles, process different ones
        5. Loop continues until no more articles

        This ensures no duplicate work across parallel workers.
        """

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

        stats = ClassificationStats()
        remaining = limit if limit else float("inf")
        attempted_article_ids: set[str] = set()

        effective_model_version = model_version or classifier.model_version or "unknown"
        effective_model_path = model_path or getattr(
            classifier, "model_identifier", None
        )
        if effective_model_path is not None:
            effective_model_path = str(effective_model_path)

        # Process in batches with row-level locking and batch commits
        while remaining > 0:
            batch_limit = min(batch_size, int(remaining)) if limit else batch_size

            excluded_ids = (
                list(attempted_article_ids) if attempted_article_ids else None
            )

            only_ids = None
            if rework:
                only_ids = self._articles_owed_a_classification(self.session)
                if not only_ids:
                    logger.info("rework: nothing owes a classification")
                    break

            # The kwarg is passed only when rework is on. Every existing
            # caller and test double of `_select_articles` predates it, and
            # a positional-only fake that is handed an unexpected keyword
            # raises before it can select anything.
            select_kwargs = {"only_article_ids": only_ids} if rework else {}
            articles = self._select_articles(
                effective_statuses,
                label_version,
                batch_limit,
                include_existing,
                list(excluded_statuses),
                excluded_ids,
                dataset_id,
                **select_kwargs,
            )

            if not articles:
                break  # No more articles to process

            stats.processed += len(articles)
            if limit:
                remaining -= len(articles)

            # Process this batch of articles
            texts: list[str] = []
            article_refs: list[Article] = []
            batch_article_ids: set[str] = set()

            for article in articles:
                article_id_value = getattr(article, "id", None)
                if article_id_value is not None:
                    batch_article_ids.add(str(article_id_value))

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

            if batch_article_ids:
                attempted_article_ids.update(batch_article_ids)

            if not texts:
                # Release any row locks before continuing
                self.session.rollback()
                continue

            try:
                predictions_batch = classifier.predict_batch(
                    texts,
                    top_k=top_k,
                )
            except Exception as exc:  # pylint: disable=broad-except
                stats.errors += len(texts)
                self.logger.exception("Classifier failed on batch: %s", exc)
                self.session.rollback()
                continue

            labeled_ids: list[str] = []
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
                    autocommit=False,
                )
                stats.labeled += 1
                labeled_ids.append(str(article_id_value))

            # A rework row is closed by the batch that labelled it, in the
            # same commit. Closed after the commit, a crash between the two
            # leaves a labelled article still "owing" work, and tomorrow
            # labels it again; closed before, a rollback leaves a row
            # closed for work that never landed.
            if rework and not dry_run:
                self._settle_rework(self.session, labeled_ids, "classified")

            # Commit batch to release locks for parallel workers
            self.session.commit()

        return stats


def _batch_iter(
    items: Sequence[Article],
    batch_size: int,
) -> Iterable[Sequence[Article]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]
