"""
Entity extraction command for backfilling entities on existing articles.

This command processes articles that have content but no entity data,
extracting location entities and storing them in the article_entities table.
"""

import logging
import threading
import time

from sqlalchemy import text as sql_text

from src.models.database import (
    DatabaseManager,
    safe_session_execute,
    save_article_entities,
)
from src.pipeline.entity_extraction import (
    ArticleEntityExtractor,
    attach_gazetteer_matches,
    get_gazetteer_rows,
)

logger = logging.getLogger(__name__)


def log_and_print(message: str, level: str = "info") -> None:
    """Log message and print to stdout with immediate flush for visibility."""
    print(message, flush=True)
    getattr(logger, level)(message)


def add_entity_extraction_parser(subparsers):
    """Add extract-entities command parser to CLI."""
    parser = subparsers.add_parser(
        "extract-entities",
        help="Extract entities from articles that have content but no entity data",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of articles to process per run (default: 100)",
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Limit to a specific source name",
    )
    parser.set_defaults(func=handle_entity_extraction_command)


def handle_entity_extraction_command(args, extractor=None) -> int:
    """Execute entity extraction command logic.

    Processes articles that have content but no entries in article_entities table.

    Args:
        args: Command arguments containing limit and source filters
        extractor: Optional pre-loaded ArticleEntityExtractor instance. If None,
                   a new extractor will be created (loading the spaCy model).
    """
    limit = getattr(args, "limit", 100)
    source = getattr(args, "source", None)

    # Log startup with visibility
    log_and_print("🚀 Starting entity extraction...")
    log_and_print(f"   Processing limit: {limit} articles")
    if source:
        log_and_print(f"   Source filter: {source}")
    log_and_print("")

    db = DatabaseManager()

    # Use provided extractor or create new one
    if extractor is None:
        log_and_print("🧠 Loading spaCy model...")
        extractor = ArticleEntityExtractor()
        log_and_print("✅ spaCy model loaded")

    try:
        with db.get_session() as session:
            # Query for articles grouped by source
            # Ordered to process sources together for efficient gazetteer caching
            query = sql_text(
                """
                SELECT a.id, a.text, a.text_hash, cl.source_id, cl.dataset_id, cl.source
                FROM articles a
                JOIN candidate_links cl ON a.candidate_link_id = cl.id
                WHERE a.content IS NOT NULL
                AND a.text IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id
                )
                AND a.status != 'error'
                """
                + ("AND cl.source = :source" if source else "")
                + """
                ORDER BY cl.source_id, cl.dataset_id
                LIMIT :limit
            """
            )

            params = {"limit": limit}
            if source:
                params["source"] = source

            result = safe_session_execute(session, query, params)
            rows = result.fetchall()

            if not rows:
                log_and_print("ℹ️  No articles found needing entity extraction")
                return 0

            log_and_print(f"📊 Found {len(rows)} articles needing entity extraction")
            
            # Group articles by source for efficient processing
            from collections import defaultdict
            articles_by_source = defaultdict(list)
            for row in rows:
                article_id, text, text_hash, source_id, dataset_id, source_name = row
                articles_by_source[(source_id, dataset_id)].append(
                    (article_id, text, text_hash, source_name)
                )
            
            num_sources = len(articles_by_source)
            log_and_print(f"   Grouped into {num_sources} source/dataset combos")
            log_and_print("")

            processed = 0
            errors = 0

            # Start timer-based progress logging
            start_time = time.time()

            def log_progress_periodically():
                """Log progress every 30 seconds regardless of article count."""
                while True:
                    time.sleep(30)
                    elapsed = time.time() - start_time
                    msg = f"⏱️ {processed}/{len(rows)} done ({elapsed:.1f}s)"
                    log_and_print(msg)

            # Start background progress logger
            progress_thread = threading.Thread(
                target=log_progress_periodically, daemon=True
            )
            progress_thread.start()

            log_and_print("🚀 Starting background progress logger (reports every 30s)")

            # Process articles source-by-source for efficient gazetteer reuse
            for (source_id, dataset_id), articles in articles_by_source.items():
                source_name = articles[0][3] if articles else "unknown"
                msg = f"📰 Processing {len(articles)} articles from {source_name}"
                log_and_print(msg)
                
                # Load gazetteer once per source
                gazetteer_rows = get_gazetteer_rows(
                    session,
                    source_id,
                    dataset_id,
                )
                log_and_print(f"   Loaded {len(gazetteer_rows)} gazetteer entries")

                for article_id, text, text_hash, _ in articles:
                    try:
                        # Extract entities from article text
                        entities = extractor.extract(
                            text,
                            gazetteer_rows=gazetteer_rows,
                        )

                        # Attach gazetteer matches
                        entities = attach_gazetteer_matches(
                            session,
                            source_id,
                            dataset_id,
                            entities,
                            gazetteer_rows=gazetteer_rows,
                        )

                        # Save entities to database
                        # Note: save_article_entities commits internally
                        save_article_entities(
                            session,
                            str(article_id),
                            entities,
                            extractor.extractor_version,
                            text_hash,
                        )

                        processed += 1

                    except Exception as exc:
                        error_msg = (
                            f"Failed to extract entities for article "
                            f"{article_id}: {exc}"
                        )
                        log_and_print(error_msg, level="error")
                        logger.exception(
                            "Failed to extract entities for article %s: %s",
                            article_id,
                            exc,
                        )
                        errors += 1
                        session.rollback()

                # Log progress after each source
                progress_msg = (
                    f"✓ Completed {source_name}: {processed}/{len(rows)} total"
                )
                log_and_print(progress_msg)

            log_and_print("")
            log_and_print("✅ Entity extraction completed!")
            log_and_print(f"   Processed: {processed} articles")
            log_and_print(f"   Errors: {errors}")
            log_and_print("")

            return 0 if errors == 0 else 1

    except Exception as exc:
        error_msg = f"Entity extraction failed: {exc}"
        log_and_print(error_msg, level="error")
        logger.exception("Entity extraction failed: %s", exc)
        return 1
