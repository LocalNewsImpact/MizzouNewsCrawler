"""Services for applying machine learning classifiers to articles."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from src.ml.article_classifier import Prediction
from src.models import Article, ArticleLabel, CandidateLink
from src.models.database import save_article_classification
from src.utils import language

#: Files a Spanish-language record terminally. `jsonb_set` with `create_missing`
#: adds the key without reading the row first, so a concurrent writer's other
#: metadata survives.
_MARK_NON_ENGLISH_SQL = sa_text(
    "UPDATE articles SET status = :status, "
    "metadata = jsonb_set(coalesce(metadata::jsonb, '{}'::jsonb), "
    "CAST(:key AS text[]), CAST(:note AS jsonb), true)::json "
    "WHERE id = :id"
)

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


#: Statuses a classification run must never take, whatever it is asked for.
#:
#: There were two of these and they disagreed. This module excluded
#: `opinion/opinions/obituary/obits/wire`; `cli/commands/analysis.py` named
#: those plus `paywall` and `not_article` but applied its copy only inside the
#: label-change REPORT, so the selection never saw the extra two. Neither list
#: knew about the terminal statuses added later. `--statuses all` therefore
#: re-labelled 32 WSU articles that had been deliberately set aside.
#:
#: Two of these are terminal by decision rather than by content:
#:   `non_english`  -- Spanish-language articles wait for a Spanish
#:                     classifier; an English model's verdict on them is
#:                     noise, and the status is the record that we know.
#:   `text_unavailable` -- the body is unusable and the row exists to record
#:                     that the publication ran the story. There is nothing
#:                     to classify.
#:
#: This is a prohibition, not a default. Naming one of these in `--statuses`
#: does not override it: the run filters it out, logs "No eligible statuses
#: after excluding ...", and classifies nothing. That is deliberate -- there is
#: no use for an English model's verdict on a Spanish article or on a row with
#: no body, and a reviewer's `not_article` is a decision, not a gap.
NEVER_CLASSIFIED: frozenset[str] = frozenset(
    {
        "opinion",
        "opinions",
        "obituary",
        "obits",
        "wire",
        "paywall",
        "not_article",
        "non_english",
        "text_unavailable",
    }
)


class ArticleClassificationService:
    """Apply text classification models to articles in the database."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def _articles_owed_a_classification(session, statuses):
        """Flagged articles holding a status this stage reads.

        The set lives in `src.pipeline.rework`: flagged AND ready, joined,
        because the status alone is the whole backlog (450 articles sit at
        `cleaned`) and the flag alone says nothing about readiness.

        An article reaches this set without anything writing a row for it:
        the flag is inherited from the link a decision rewound, so a link
        fetched earlier in the same run is classified later in it.
        """
        from src.pipeline.rework import articles_in

        return articles_in(session, statuses)

    @staticmethod
    def _settle_rework(session, record_ids=None, outcome=None):
        """Close the rows of records with nothing left owing.

        Settled on the status, centrally, and NOT by queueing the next
        stage: the first version wrote an `enrich` row here, which put the
        handoff in two places and fired on a status the article might not
        hold yet.
        """
        from src.pipeline.rework import settle

        return settle(session)

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

        # A LABEL DESCRIBES THE BODY IT WAS MADE FROM. One applied before the
        # article's latest extraction was computed on a capture that no longer
        # exists, so it does not count as existing.
        #
        # 2026-09-21: 17 WSU articles sat at `cleaned` with labels. Each was
        # first captured as a paywall or navigation page, classified, then
        # refetched by the authenticated rotation -- which put the status back to
        # `cleaned` -- and skipped here because a label existed. Enrichment
        # selects on `labeled`, so they could never be enriched, and the label
        # they carried was for the wall. Re-run on the real bodies, 4 of the 17
        # changed category.
        if not include_existing:
            label_exists = (
                select(ArticleLabel.id)
                .where(
                    ArticleLabel.article_id == Article.id,
                    ArticleLabel.label_version == label_version,
                    ArticleLabel.applied_at >= Article.extracted_at,
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
    _BODY_FIELD_PREFERENCE = ("text", "raw")

    def _body_field(self, article: Article) -> str | None:
        """The body this stage would classify, before any language filtering."""
        for field_name in self._BODY_FIELD_PREFERENCE:
            value = getattr(article, field_name, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _prepare_text(self, article: Article) -> str | None:
        """Headline plus cleaned body — the two together, not the first of them.

        A headline is a dense statement of what a story is about, which is
        exactly the judgement the CIN classifier makes, so it is prepended to
        the body rather than used only as a last resort. Either part may be
        missing; whatever is present is classified.

        ENGLISH ONLY. The body passes through `language.analysis_text`, so a
        bilingual article is classified on its English paragraphs rather than
        on both languages at once -- `redlatinastl.com` runs every story twice
        on one page, and those bodies measure 46-57% Spanish by paragraph. A
        Spanish-language body returns None and the caller files the record as
        non-English instead of classifying it.
        """
        parts: list[str] = []

        title = getattr(article, "title", None)
        if isinstance(title, str) and title.strip():
            parts.append(title.strip())

        body = language.analysis_text(self._body_field(article))
        if isinstance(body, str) and body.strip():
            parts.append(body.strip())

        return "\n\n".join(parts) if parts else None

    def _mark_non_english(
        self, article_id: str, found: language.LanguageProfile
    ) -> None:
        """File a Spanish-language record so it stops being offered for work.

        Without this the article keeps its eligible status, is re-selected on
        every run and skipped again forever: `attempted_article_ids` only
        suppresses a repeat inside ONE run.

        The status is TERMINAL -- see `language.NON_ENGLISH_STATUS`. Nothing
        here rewinds or retries it, because a second fetch returns the same
        Spanish page. The verdict goes to `metadata.language` as well, so the
        Spanish classifier this is waiting on can find its corpus by query.

        Written through the session rather than by assigning to the model, as
        `save_article_classification` does, and with `jsonb_set` so a sibling
        metadata key is not clobbered by a read-modify-write.
        """
        note = json.dumps(
            {
                "primary": language.SPANISH,
                "verdict": found.verdict,
                "spanish_share": round(found.spanish_share, 4),
                "english_chars": found.english_chars,
                "spanish_chars": found.spanish_chars,
                "detector": "function_word_rate_by_paragraph",
            }
        )
        self.session.execute(
            _MARK_NON_ENGLISH_SQL,
            {
                "id": article_id,
                "status": language.NON_ENGLISH_STATUS,
                "key": "{" + language.LANGUAGE_METADATA_KEY + "}",
                "note": note,
            },
        )
        self.logger.info(
            "Article %s is Spanish (%.0f%% of measured text); filed as %s",
            article_id,
            found.spanish_share * 100,
            language.NON_ENGLISH_STATUS,
        )

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

        excluded_statuses = set(NEVER_CLASSIFIED)
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
                # The statuses this run reads, joined to the flag. Passing
                # them in is what keeps the two halves of the set in one
                # place: this stage decides which statuses it wants, and
                # `src.pipeline.rework` decides who is flagged.
                only_ids = self._articles_owed_a_classification(
                    self.session, effective_statuses
                )
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
                    # Only recomputed on the skip path, which is the minority.
                    found = language.profile(self._body_field(article))
                    article_id_value = getattr(article, "id", None)
                    if found.verdict == "spanish" and article_id_value:
                        self._mark_non_english(str(article_id_value), found)
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

            # Rows are closed on the record's STATUS, so an article this
            # batch moved to `labeled` keeps its row and the enrich step of
            # the same run takes it. One that reached a terminal status --
            # an unenriched kind, say -- is closed here with that status as
            # its outcome.
            if rework and not dry_run:
                self._settle_rework(self.session)

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
