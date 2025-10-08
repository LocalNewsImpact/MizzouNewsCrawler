"""
Entity extraction command for backfilling entities on existing articles.

This command processes articles that have content but no entity data,
extracting location entities and storing them in the article_entities table.
"""

import logging
from typing import cast

from sqlalchemy import text as sql_text

from src.models.database import DatabaseManager, save_article_entities
from src.pipeline.entity_extraction import (
    ArticleEntityExtractor,
    attach_gazetteer_matches,
    get_gazetteer_rows,
)

logger = logging.getLogger(__name__)


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


def handle_entity_extraction_command(args) -> int:
    """Execute entity extraction command logic.
    
    Processes articles that have content but no entries in article_entities table.
    """
    limit = getattr(args, "limit", 100)
    source = getattr(args, "source", None)
    
    # Print to stdout immediately for visibility
    print(f"🚀 Starting entity extraction...")
    print(f"   Processing limit: {limit} articles")
    if source:
        print(f"   Source filter: {source}")
    print()
    
    logger.info("Starting entity extraction for articles without entities")
    logger.info("Processing limit: %d articles", limit)
    
    db = DatabaseManager()
    extractor = ArticleEntityExtractor()
    
    try:
        with db.get_session() as session:
            # Query for articles with content but no entities
            query = sql_text("""
                SELECT a.id, a.text, a.text_hash, a.source_id, a.dataset_id
                FROM articles a
                WHERE a.content IS NOT NULL
                AND a.text IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id
                )
                AND a.status != 'error'
                """ + ("AND a.source = :source" if source else "") + """
                LIMIT :limit
            """)
            
            params = {"limit": limit}
            if source:
                params["source"] = source
            
            result = session.execute(query, params)
            rows = result.fetchall()
            
            if not rows:
                print("✓ No articles found needing entity extraction")
                logger.info("No articles found needing entity extraction")
                return 0
            
            print(f"📊 Found {len(rows)} articles needing entity extraction")
            logger.info("Found %d articles needing entity extraction", len(rows))
            
            processed = 0
            errors = 0
            
            for row in rows:
                article_id, text, text_hash, source_id, dataset_id = row
                
                try:
                    # Get gazetteer rows for this source
                    gazetteer_rows = get_gazetteer_rows(
                        session,
                        source_id,
                        dataset_id,
                    )
                    
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
                    save_article_entities(
                        session,
                        cast(str, article_id),
                        entities,
                        extractor.extractor_version,
                        cast(str | None, text_hash),
                    )
                    
                    processed += 1
                    
                    if processed % 10 == 0:
                        print(f"✓ Progress: {processed}/{len(rows)} articles processed")
                        logger.info(
                            "Progress: %d/%d articles processed",
                            processed,
                            len(rows),
                        )
                        session.commit()
                
                except Exception as exc:
                    logger.exception(
                        "Failed to extract entities for article %s: %s",
                        article_id,
                        exc,
                    )
                    errors += 1
                    session.rollback()
            
            # Final commit
            session.commit()
            
            print()
            print(f"✅ Entity extraction completed!")
            print(f"   Processed: {processed} articles")
            print(f"   Errors: {errors}")
            
            logger.info(
                "Entity extraction completed: %d processed, %d errors",
                processed,
                errors,
            )
            
            return 0 if errors == 0 else 1
    
    except Exception as exc:
        logger.exception("Entity extraction failed: %s", exc)
        return 1
