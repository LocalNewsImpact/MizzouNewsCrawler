#!/usr/bin/env python3
"""
Clean up duplicate URLs in candidate_links and articles tables.

Duplicates arise from http/https and www/non-www URL variations.
This script:
1. Identifies duplicate URL groups (after normalization)
2. Keeps the oldest record
3. Deletes newer duplicates

Run with --dry-run first to see what would be deleted.
"""

import argparse
import logging

from sqlalchemy import text

from src.models.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def normalize_url_sql(url_column: str) -> str:
    """Generate SQL to normalize URL (strip http/https and www.)"""
    return f"""
        REGEXP_REPLACE(
            REGEXP_REPLACE({url_column}, '^https?://', ''),
            '^www\\.', ''
        )
    """


def find_candidate_link_duplicates(session):
    """Find duplicate candidate_links by normalized URL."""
    query = text(f"""
        WITH normalized AS (
            SELECT 
                id,
                url,
                discovered_at,
                {normalize_url_sql('url')} as norm_url
            FROM candidate_links
        ),
        dup_groups AS (
            SELECT norm_url, MIN(discovered_at) as first_discovered
            FROM normalized
            GROUP BY norm_url
            HAVING COUNT(*) > 1
        )
        SELECT 
            n.id, 
            n.url, 
            n.discovered_at,
            d.first_discovered
        FROM normalized n
        JOIN dup_groups d ON n.norm_url = d.norm_url
        WHERE n.discovered_at > d.first_discovered
        ORDER BY n.norm_url, n.discovered_at
    """)
    return session.execute(query).fetchall()


def find_article_duplicates(session):
    """Find duplicate articles by normalized URL."""
    query = text(f"""
        WITH normalized AS (
            SELECT 
                id,
                url,
                extracted_at,
                candidate_link_id,
                {normalize_url_sql('url')} as norm_url
            FROM articles
        ),
        dup_groups AS (
            SELECT norm_url, MIN(extracted_at) as first_extracted
            FROM normalized
            GROUP BY norm_url
            HAVING COUNT(*) > 1
        )
        SELECT 
            n.id, 
            n.url, 
            n.extracted_at,
            n.candidate_link_id,
            d.first_extracted
        FROM normalized n
        JOIN dup_groups d ON n.norm_url = d.norm_url
        WHERE n.extracted_at > d.first_extracted
        ORDER BY n.norm_url, n.extracted_at
    """)
    return session.execute(query).fetchall()


def delete_article_dependencies(session, article_ids: list, dry_run: bool = True):
    """Delete article dependencies (labels, entities, locations)."""
    if not article_ids:
        return
    
    ids_str = ",".join(f"'{aid}'" for aid in article_ids)
    
    tables = ['article_labels', 'article_entities', 'locations']
    for table in tables:
        count_query = text(f"SELECT COUNT(*) FROM {table} WHERE article_id IN ({ids_str})")
        count = session.execute(count_query).scalar()
        if count > 0:
            logger.info(f"  {table}: {count} records to delete")
            if not dry_run:
                session.execute(text(f"DELETE FROM {table} WHERE article_id IN ({ids_str})"))


def main():
    parser = argparse.ArgumentParser(description='Clean up duplicate URLs')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without actually deleting')
    parser.add_argument('--articles-only', action='store_true', help='Only clean up articles, not candidate_links')
    parser.add_argument('--candidate-links-only', action='store_true', help='Only clean up candidate_links, not articles')
    args = parser.parse_args()
    
    db = DatabaseManager()
    
    with db.get_session() as session:
        # Clean up articles first (they reference candidate_links)
        if not args.candidate_links_only:
            logger.info("Finding duplicate articles...")
            article_dups = find_article_duplicates(session)
            logger.info(f"Found {len(article_dups)} duplicate articles to remove")
            
            if article_dups:
                # Show first 10
                for dup in article_dups[:10]:
                    logger.info(f"  Will delete: {dup[1][:60]}... (extracted: {dup[2]})")
                if len(article_dups) > 10:
                    logger.info(f"  ... and {len(article_dups) - 10} more")
                
                article_ids = [str(dup[0]) for dup in article_dups]
                
                # Delete dependencies
                logger.info("Deleting article dependencies...")
                delete_article_dependencies(session, article_ids, args.dry_run)
                
                if not args.dry_run:
                    ids_str = ",".join(f"'{aid}'" for aid in article_ids)
                    session.execute(text(f"DELETE FROM articles WHERE id IN ({ids_str})"))
                    logger.info(f"Deleted {len(article_ids)} duplicate articles")
        
        # Clean up candidate_links
        if not args.articles_only:
            logger.info("Finding duplicate candidate_links...")
            cl_dups = find_candidate_link_duplicates(session)
            logger.info(f"Found {len(cl_dups)} duplicate candidate_links to remove")
            
            if cl_dups:
                # Show first 10
                for dup in cl_dups[:10]:
                    logger.info(f"  Will delete: {dup[1][:60]}... (discovered: {dup[2]})")
                if len(cl_dups) > 10:
                    logger.info(f"  ... and {len(cl_dups) - 10} more")
                
                if not args.dry_run:
                    cl_ids = [str(dup[0]) for dup in cl_dups]
                    ids_str = ",".join(f"'{clid}'" for clid in cl_ids)
                    
                    # First check if any articles reference these candidate_links
                    refs = session.execute(text(f"""
                        SELECT COUNT(*) FROM articles 
                        WHERE candidate_link_id IN ({ids_str})
                    """)).scalar()
                    
                    if refs > 0:
                        logger.warning(f"  {refs} articles still reference these candidate_links - skipping deletion")
                    else:
                        session.execute(text(f"DELETE FROM candidate_links WHERE id IN ({ids_str})"))
                        logger.info(f"Deleted {len(cl_ids)} duplicate candidate_links")
        
        if not args.dry_run:
            session.commit()
            logger.info("Changes committed")
        else:
            logger.info("DRY RUN - no changes made")


if __name__ == '__main__':
    main()
