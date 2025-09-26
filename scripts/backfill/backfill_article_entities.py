#!/usr/bin/env python3
"""Backfill structured entity extraction results for existing articles."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from typing import List, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from src.cli.commands import extraction as extraction_commands
from src.models import Article, ArticleEntity, CandidateLink
from src.models.database import DatabaseManager
from src.pipeline.entity_extraction import ArticleEntityExtractor

logger = logging.getLogger(__name__)


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - argparse surfaces error
        raise argparse.ArgumentTypeError(
            "Expected ISO 8601 datetime value (e.g. 2025-09-24T12:34:00)"
        ) from exc


def _build_article_query(
    session: Session,
    extractor_version: str,
    *,
    include_wire: bool,
    statuses: Sequence[str] | None,
    source: str | None,
    dataset_id: str | None,
    since: datetime | None,
) -> Query:
    """Return a SQLAlchemy query selecting article IDs that need entities."""

    query = (
        session.query(Article.id)
        .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
    )

    if not include_wire:
        query = query.filter(
            or_(Article.status.is_(None), Article.status != "wire")
        )

    if statuses:
        query = query.filter(Article.status.in_(list(statuses)))

    if source:
        query = query.filter(CandidateLink.source == source)

    if dataset_id:
        query = query.filter(CandidateLink.dataset_id == dataset_id)

    if since:
        query = query.filter(Article.extracted_at >= since)

    # Require text or content to exist to avoid wasting extractor cycles
    query = query.filter(
        or_(Article.text.isnot(None), Article.content.isnot(None))
    )

    current_entities = (
        session.query(ArticleEntity.id)
        .filter(
            ArticleEntity.article_id == Article.id,
            ArticleEntity.extractor_version == extractor_version,
            or_(
                Article.text_hash.is_(None),
                ArticleEntity.article_text_hash == Article.text_hash,
            ),
        )
        .exists()
    )

    query = query.filter(~current_entities)
    query = query.order_by(Article.extracted_at.asc(), Article.id.asc())
    return query


def run_backfill(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    extractor = ArticleEntityExtractor(model_name=args.model)
    extraction_commands._ENTITY_EXTRACTOR = extractor

    db = DatabaseManager()
    session = db.session

    try:
        base_query = _build_article_query(
            session,
            extractor.extractor_version,
            include_wire=args.include_wire,
            statuses=args.statuses,
            source=args.source,
            dataset_id=args.dataset_id,
            since=args.since,
        )

        total_candidates = base_query.count()
        logger.info(
            "Found %d article(s) needing entity refresh (extractor=%s)",
            total_candidates,
            extractor.extractor_version,
        )

        effective_query = base_query
        if args.limit is not None:
            effective_query = effective_query.limit(args.limit)

        if args.dry_run:
            planned_total = (
                total_candidates
                if args.limit is None
                else min(total_candidates, args.limit)
            )
            preview_n = min(args.preview, planned_total)
            if preview_n > 0:
                preview_ids = [
                    row[0] for row in effective_query.limit(preview_n).all()
                ]
            else:
                preview_ids = []
            logger.info(
                "Dry run: would process %d article(s)",
                planned_total,
            )
            if preview_ids:
                logger.info(
                    "Sample article IDs: %s",
                    ", ".join(preview_ids),
                )
            return

        processed = 0
        pending_ids: List[str] = []

        for row in effective_query.yield_per(args.batch_size):
            article_id = row[0]
            if not isinstance(article_id, str):
                article_id = str(article_id)
            pending_ids.append(article_id)
            if len(pending_ids) >= args.batch_size:
                _process_batch(pending_ids)
                processed += len(pending_ids)
                pending_ids = []

        if pending_ids:
            _process_batch(pending_ids)
            processed += len(pending_ids)

        logger.info(
            "Entity backfill complete; processed %d article(s).",
            processed,
        )
    finally:
        session.close()


def _process_batch(article_ids: Sequence[str]) -> None:
    logger.info(
        "Processing entity extraction for %d article(s)",
        len(article_ids),
    )
    extraction_commands._run_article_entity_extraction(article_ids)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill article entity extraction results"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of articles to process",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of article IDs to process per batch (default: 50)",
    )
    parser.add_argument(
        "--source",
        help="Filter by CandidateLink.source",
    )
    parser.add_argument(
        "--dataset-id",
        help="Filter by CandidateLink.dataset_id",
    )
    parser.add_argument(
        "--status",
        dest="statuses",
        action="append",
        help="Restrict to specific article status (repeatable)",
    )
    parser.add_argument(
        "--include-wire",
        action="store_true",
        help="Include articles marked as wire content",
    )
    parser.add_argument(
        "--since",
        type=_parse_datetime,
        help="Only process articles extracted at or after this ISO timestamp",
    )
    parser.add_argument(
        "--model",
        default="en_core_web_sm",
        help="spaCy model name to load for entity extraction",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many articles would be processed without writing",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=10,
        help="How many article IDs to show during dry-run (default: 10)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    run_backfill(args)


if __name__ == "__main__":
    main()
