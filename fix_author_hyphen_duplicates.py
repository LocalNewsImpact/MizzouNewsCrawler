#!/usr/bin/env python3
"""
Fix hyphen/space duplicate authors in the articles table.

This script applies the enhanced _deduplicate_authors logic to existing records
in the database, removing hyphenated duplicates while preserving non-hyphenated
versions and legitimate hyphenated names.
"""

import sqlite3
import json
import logging
from typing import List
from src.utils.byline_cleaner import BylineCleaner

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_hyphen_duplicates(authors: List[str]) -> List[str]:
    """
    Apply the same deduplication logic as the enhanced BylineCleaner.
    
    Args:
        authors: List of author names that may contain hyphen/space duplicates
        
    Returns:
        Deduplicated list with hyphenated duplicates removed
    """
    if not authors or len(authors) <= 1:
        return authors
    
    # Use the enhanced deduplication logic from BylineCleaner
    cleaner = BylineCleaner(enable_telemetry=False)
    return cleaner._deduplicate_authors(authors)


def update_articles_with_hyphen_duplicates(
        db_path: str, dry_run: bool = True) -> None:
    """
    Update articles that have hyphen/space duplicate authors.
    
    Args:
        db_path: Path to the SQLite database
        dry_run: If True, only show what would be changed without making
                 updates
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Find articles with hyphen duplicates
        logger.info("Finding articles with hyphen/space duplicate authors...")
        cursor.execute("""
            SELECT id, title, author
            FROM articles
            WHERE author IS NOT NULL
            AND author != '[]'
            AND author != 'null'
        """)
        
        all_articles = cursor.fetchall()
        articles_to_update = []
        
        for article_id, title, author_json in all_articles:
            if not author_json or author_json.strip() in ['[]', 'null', '']:
                continue
            
            try:
                authors = json.loads(author_json)
                if isinstance(authors, list) and len(authors) > 1:
                    # Check for hyphen/space duplicates
                    has_duplicates = False
                    for i, author1 in enumerate(authors):
                        for j, author2 in enumerate(authors):
                            if i != j:
                                # Compare after normalizing hyphens to spaces
                                norm1 = author1.replace('-', ' ')
                                norm1 = norm1.replace('–', ' ')
                                norm1 = norm1.replace('—', ' ')
                                norm2 = author2.replace('-', ' ')
                                norm2 = norm2.replace('–', ' ')
                                norm2 = norm2.replace('—', ' ')
                                if norm1 == norm2:
                                    has_duplicates = True
                                    break
                        if has_duplicates:
                            break
                    
                    if has_duplicates:
                        # Apply the fix
                        fixed_authors = find_hyphen_duplicates(authors)
                        articles_to_update.append({
                            'id': article_id,
                            'title': title[:50] if title else 'No title',
                            'original_authors': authors,
                            'fixed_authors': fixed_authors
                        })
                        
            except (json.JSONDecodeError, TypeError) as e:
                msg = f"Skipping article {article_id} due to JSON error: {e}"
                logger.warning(msg)
                continue
        
        found_count = len(articles_to_update)
        logger.info(f"Found {found_count} articles that need fixing")
        
        if not articles_to_update:
            logger.info("No articles need updating!")
            return
        
        # Show what would be changed
        logger.info("\n=== Preview of changes ===")
        for i, article in enumerate(articles_to_update[:10], 1):
            logger.info(f"{i}. Article {article['id']}: {article['title']}...")
            logger.info(f"   Original: {article['original_authors']}")
            logger.info(f"   Fixed:    {article['fixed_authors']}")
            orig_count = len(article['original_authors'])
            fixed_count = len(article['fixed_authors'])
            removed_count = orig_count - fixed_count
            logger.info(f"   Removed {removed_count} duplicate(s)")
        
        if len(articles_to_update) > 10:
            remaining = len(articles_to_update) - 10
            logger.info(f"... and {remaining} more articles")
        
        if dry_run:
            logger.info("\n=== DRY RUN MODE - No changes made ===")
            logger.info(f"Would update {len(articles_to_update)} articles")
            return
        
        # Apply the fixes
        logger.info(f"\n=== Applying fixes to {len(articles_to_update)} articles ===")
        
        updated_count = 0
        for article in articles_to_update:
            try:
                fixed_json = json.dumps(article['fixed_authors'])
                cursor.execute("""
                    UPDATE articles 
                    SET author = ? 
                    WHERE id = ?
                """, (fixed_json, article['id']))
                
                updated_count += 1
                
                if updated_count % 10 == 0:
                    logger.info(f"Updated {updated_count}/{len(articles_to_update)} articles...")
                    
            except Exception as e:
                logger.error(f"Error updating article {article['id']}: {e}")
                continue
        
        # Commit the changes
        conn.commit()
        logger.info(f"\n✅ Successfully updated {updated_count} articles!")
        
        # Verify the changes
        logger.info("\n=== Verifying changes ===")
        cursor.execute("""
            SELECT COUNT(*) 
            FROM articles 
            WHERE author IS NOT NULL 
            AND author != '[]' 
            AND author != 'null'
        """)
        total_with_authors = cursor.fetchone()[0]
        
        # Count remaining duplicates
        cursor.execute("""
            SELECT id, author 
            FROM articles 
            WHERE author IS NOT NULL 
            AND author != '[]' 
            AND author != 'null'
        """)
        
        remaining_duplicates = 0
        for article_id, author_json in cursor.fetchall():
            try:
                authors = json.loads(author_json)
                if isinstance(authors, list) and len(authors) > 1:
                    for i, author1 in enumerate(authors):
                        for j, author2 in enumerate(authors):
                            if i != j:
                                norm1 = author1.replace('-', ' ').replace('–', ' ').replace('—', ' ')
                                norm2 = author2.replace('-', ' ').replace('–', ' ').replace('—', ' ')
                                if norm1 == norm2:
                                    remaining_duplicates += 1
                                    break
                        else:
                            continue
                        break
            except (json.JSONDecodeError, TypeError):
                continue
        
        logger.info(f"Remaining articles with hyphen duplicates: {remaining_duplicates}")
        logger.info(f"Total articles with authors: {total_with_authors}")
        
        if remaining_duplicates == 0:
            logger.info("🎉 All hyphen/space duplicates have been successfully removed!")
        
    except Exception as e:
        logger.error(f"Error during processing: {e}")
        conn.rollback()
        raise
    
    finally:
        conn.close()

def main():
    """Main function to run the fix."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix hyphen/space duplicate authors in articles table')
    parser.add_argument('--db-path', default='data/mizzou.db', 
                       help='Path to the SQLite database (default: data/mizzou.db)')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be changed without making updates')
    parser.add_argument('--apply', action='store_true', 
                       help='Apply the fixes to the database')
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.apply:
        logger.info("Use --dry-run to preview changes or --apply to make updates")
        parser.print_help()
        return
    
    dry_run = args.dry_run or not args.apply
    
    logger.info(f"Starting hyphen duplicate fix...")
    logger.info(f"Database: {args.db_path}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'APPLY CHANGES'}")
    
    update_articles_with_hyphen_duplicates(args.db_path, dry_run=dry_run)

if __name__ == '__main__':
    main()