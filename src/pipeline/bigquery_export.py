"""
BigQuery export module for MizzouNewsCrawler.

Exports article data from PostgreSQL to BigQuery for analytics.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict

from google.cloud import bigquery
from sqlalchemy import text

from src.models.database import DatabaseManager

logger = logging.getLogger(__name__)

# BigQuery configuration
PROJECT_ID = "mizzou-news-crawler"
DATASET_ID = "mizzou_analytics"


def get_bigquery_client() -> bigquery.Client:
    """Get BigQuery client."""
    return bigquery.Client(project=PROJECT_ID)


def export_articles_to_bigquery(
    days_back: int = 7,
    batch_size: int = 1000,
    full_export: bool = False
) -> Dict[str, int]:
    """
    Export articles from PostgreSQL to BigQuery.
    
    Args:
        days_back: Number of days to look back for articles (ignored if full_export=True)
        batch_size: Number of rows to process at once
        full_export: If True, export all articles regardless of date
        
    Returns:
        Dictionary with export statistics
    """
    if full_export:
        logger.info("Starting full BigQuery export (all articles)")
    else:
        logger.info(f"Starting BigQuery export for articles from last {days_back} days")
    
    # Create database manager (handles Cloud SQL Connector automatically)
    db_manager = DatabaseManager()
    engine = db_manager.engine
    bq_client = get_bigquery_client()
    
    # Calculate date range (or None for full export)
    if full_export:
        start_date = None
        end_date = None
    else:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days_back)
    
    stats = {
        "articles_exported": 0,
        "cin_labels_exported": 0,
        "entities_exported": 0,
        "errors": 0
    }
    
    try:
        # Export articles
        articles_exported = _export_articles(
            engine, bq_client, start_date, end_date, batch_size
        )
        stats["articles_exported"] = articles_exported
        logger.info(f"Exported {articles_exported} articles")
        
        # Export CIN labels
        cin_labels_exported = _export_cin_labels(
            engine, bq_client, start_date, end_date, batch_size
        )
        stats["cin_labels_exported"] = cin_labels_exported
        logger.info(f"Exported {cin_labels_exported} CIN labels")
        
        # Export entities
        entities_exported = _export_entities(
            engine, bq_client, start_date, end_date, batch_size
        )
        stats["entities_exported"] = entities_exported
        logger.info(f"Exported {entities_exported} entities")
        
    except Exception as e:
        logger.error(f"Error during BigQuery export: {e}", exc_info=True)
        stats["errors"] += 1
        raise
    
    logger.info(f"BigQuery export complete: {stats}")
    return stats


def _export_articles(
    engine,
    bq_client: bigquery.Client,
    start_date: datetime | None,
    end_date: datetime | None,
    batch_size: int
) -> int:
    """Export articles table to BigQuery."""
    
    table_id = f"{PROJECT_ID}.{DATASET_ID}.articles"
    
    # Build WHERE clause based on whether dates are provided
    if start_date and end_date:
        where_clause = """
        WHERE a.extracted_at BETWEEN :start_date AND :end_date
            AND a.extracted_at IS NOT NULL
        """
        params = {"start_date": start_date, "end_date": end_date, "batch_size": batch_size}
    else:
        where_clause = "WHERE a.extracted_at IS NOT NULL"
        params = {"batch_size": batch_size}
    
    # Query to fetch articles with candidate_links for source info
    query = text(f"""
        SELECT
            a.id,
            a.url,
            cl.source_id,
            a.title,
            a.author as authors,
            a.publish_date as published_date,
            cl.discovered_at as discovered_date,
            a.extracted_at as extracted_date,
            a.text,
            a.text_excerpt as summary,
            CASE WHEN a.text IS NOT NULL
                 THEN LENGTH(a.text)
                 ELSE 0
            END as word_count,
            cl.source_county as county,
            'MO' as state,
            cl.source_name,
            cl.source as source_url,
            cl.source_type,
            a.status as extraction_status,
            a.extraction_version as extraction_method,
            a.created_at,
            a.created_at as updated_at
        FROM articles a
        LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id
        {where_clause}
        ORDER BY a.id
        LIMIT :batch_size
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, params)
        rows = result.fetchall()
    
    if not rows:
        logger.info("No articles to export")
        return 0
    
    # Convert to BigQuery format
    bq_rows = []
    for row in rows:
        # Convert UUIDs to strings
        row_id = str(row.id) if row.id else None
        source_id = str(row.source_id) if row.source_id else None
        
        # Handle authors field - ensure it's always a string, never an array
        authors = row.authors
        if isinstance(authors, list):
            authors = ", ".join(authors) if authors else None
        elif not authors:
            authors = None
            
        bq_row = {
            "id": row_id,
            "url": row.url,
            "source_id": source_id,
            "title": row.title,
            "authors": authors,
            "published_date": (
                row.published_date.isoformat()
                if row.published_date else None
            ),
            "discovered_date": (
                row.discovered_date.isoformat()
                if row.discovered_date else None
            ),
            "extracted_date": (
                row.extracted_date.isoformat()
                if row.extracted_date else None
            ),
            "text": row.text,
            "summary": row.summary,
            "word_count": row.word_count,
            "county": row.county,
            "state": row.state,
            "source_name": row.source_name,
            "source_url": row.source_url,
            "source_type": row.source_type,
            "extraction_status": row.extraction_status,
            "extraction_method": row.extraction_method,
            "created_at": (
                row.created_at.isoformat()
                if row.created_at else None
            ),
            "updated_at": (
                row.updated_at.isoformat()
                if row.updated_at else None
            ),
        }
        bq_rows.append(bq_row)
    
    if not bq_rows:
        return 0
    
    # Get existing article IDs to avoid duplicates
    existing_ids_query = f"""
    SELECT id
    FROM `{table_id}`
    WHERE id IN UNNEST(@article_ids)
    """
    
    article_ids = [row["id"] for row in bq_rows]
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("article_ids", "STRING", article_ids)
        ]
    )
    
    existing_ids = set()
    try:
        query_job = bq_client.query(existing_ids_query, job_config=job_config)
        for row in query_job:
            existing_ids.add(row.id)
    except Exception as e:
        logger.warning(f"Could not check for existing articles: {e}")
        # Continue anyway - worst case we get duplicates
    
    # Filter out articles that already exist
    new_rows = [row for row in bq_rows if row["id"] not in existing_ids]
    
    if not new_rows:
        logger.info(f"All {len(bq_rows)} articles already exist in BigQuery")
        return 0
    
    logger.info(
        f"Inserting {len(new_rows)} new articles "
        f"(skipping {len(existing_ids)} existing)"
    )
    
    # Insert only new rows
    errors = bq_client.insert_rows_json(table_id, new_rows)
    if errors:
        logger.error(f"Errors inserting articles into BigQuery: {errors}")
        raise Exception(f"BigQuery insert failed: {errors}")
    
    return len(new_rows)


def _export_cin_labels(
    engine,
    bq_client: bigquery.Client,
    start_date: datetime,
    end_date: datetime,
    batch_size: int
) -> int:
    """Export CIN labels to BigQuery."""
    
    table_id = f"{PROJECT_ID}.{DATASET_ID}.cin_labels"
    
    query = text("""
        SELECT
            l.article_id,
            l.primary_label as label,
            l.primary_label_confidence as confidence,
            l.label_version as version,
            l.model_version as model,
            a.url as article_url,
            a.title as article_title,
            a.publish_date as published_date,
            l.applied_at as created_at
        FROM article_labels l
        JOIN articles a ON l.article_id = a.id
        WHERE a.extracted_at BETWEEN :start_date AND :end_date
            AND a.extracted_at IS NOT NULL
        ORDER BY l.id
        LIMIT :batch_size
    """)
    
    with engine.connect() as conn:
        result = conn.execute(
            query,
            {"start_date": start_date, "end_date": end_date, "batch_size": batch_size}
        )
        rows = result.fetchall()
    
    if not rows:
        logger.info("No CIN labels to export")
        return 0
    
    bq_rows = []
    for row in rows:
        # Convert UUIDs to strings
        article_id = str(row.article_id) if row.article_id else None
        
        bq_row = {
            "article_id": article_id,
            "label": row.label,
            "confidence": float(row.confidence) if row.confidence else None,
            "version": row.version,
            "model": row.model,
            "article_url": row.article_url,
            "article_title": row.article_title,
            "published_date": (
                row.published_date.isoformat()
                if row.published_date else None
            ),
            "created_at": (
                row.created_at.isoformat()
                if row.created_at else None
            ),
        }
        bq_rows.append(bq_row)
    
    errors = bq_client.insert_rows_json(table_id, bq_rows)
    if errors:
        logger.error(f"Errors inserting CIN labels into BigQuery: {errors}")
        raise Exception(f"BigQuery insert failed: {errors}")
    
    return len(bq_rows)


def _export_entities(
    engine,
    bq_client: bigquery.Client,
    start_date: datetime,
    end_date: datetime,
    batch_size: int
) -> int:
    """Export entities to BigQuery."""
    
    table_id = f"{PROJECT_ID}.{DATASET_ID}.entities"
    
    query = text("""
        SELECT
            e.article_id,
            e.entity_label as entity_type,
            e.entity_text,
            e.confidence,
            NULL as start_char,
            NULL as end_char,
            a.url as article_url,
            a.title as article_title,
            e.created_at
        FROM article_entities e
        JOIN articles a ON e.article_id = a.id
        WHERE a.extracted_at BETWEEN :start_date AND :end_date
            AND a.extracted_at IS NOT NULL
        ORDER BY e.id
        LIMIT :batch_size
    """)
    
    with engine.connect() as conn:
        result = conn.execute(
            query,
            {"start_date": start_date, "end_date": end_date, "batch_size": batch_size}
        )
        rows = result.fetchall()
    
    if not rows:
        logger.info("No entities to export")
        return 0
    
    bq_rows = []
    for row in rows:
        # Convert UUIDs to strings
        article_id = str(row.article_id) if row.article_id else None
        
        bq_row = {
            "article_id": article_id,
            "entity_type": row.entity_type,
            "entity_text": row.entity_text,
            "confidence": float(row.confidence) if row.confidence else None,
            "start_char": row.start_char,
            "end_char": row.end_char,
            "article_url": row.article_url,
            "article_title": row.article_title,
            "created_at": (
                row.created_at.isoformat()
                if row.created_at else None
            ),
        }
        bq_rows.append(bq_row)
    
    errors = bq_client.insert_rows_json(table_id, bq_rows)
    if errors:
        logger.error(f"Errors inserting entities into BigQuery: {errors}")
        raise Exception(f"BigQuery insert failed: {errors}")
    
    return len(bq_rows)


if __name__ == "__main__":
    # For testing
    logging.basicConfig(level=logging.INFO)
    stats = export_articles_to_bigquery(days_back=7)
    print(f"Export complete: {stats}")
