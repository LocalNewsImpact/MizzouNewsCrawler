#!/usr/bin/env python3
"""
Script to re-clean article author names using updated byline cleaning rules.

This script fixes the byline truncation bug where organization names were
incorrectly removing parts of author names.

Usage:
    python scripts/reclean_article_authors.py [--dry-run] [--limit N]
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.byline_cleaner import BylineCleaner


def setup_logging():
    """Setup logging configuration."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = f"data/reclean_authors_{timestamp}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info("Starting article author re-cleaning process")
    logger.info(f"Log file: {log_file}")
    return logger


def create_backup(db_path, logger):
    """Create a backup of the articles table."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_id = f"articles_backup_{timestamp}"
    
    logger.info(f"Creating backup: {backup_id}")
    
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"CREATE TABLE {backup_id} AS SELECT * FROM articles")
        logger.info(f"Backup created successfully: {backup_id}")
    
    return backup_id


def get_articles_to_reclean(db_path, limit=None):
    """Get articles that need re-cleaning."""
    query = """
        SELECT DISTINCT
            a.id as article_id,
            a.author as current_author,
            bct.raw_byline,
            bct.source_name,
            cl.source_name as candidate_source_name
        FROM articles a
        JOIN byline_cleaning_telemetry bct ON a.id = bct.article_id
        LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE bct.raw_byline IS NOT NULL 
        AND bct.raw_byline != ''
        AND a.author IS NOT NULL
        AND a.author != ''
        ORDER BY a.id
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def clean_author_byline(cleaner, article_data):
    """Clean a single article's byline."""
    raw_byline = article_data['raw_byline']
    source_name = (article_data['source_name'] or 
                  article_data['candidate_source_name'])
    
    # Clean using improved BylineCleaner
    cleaned_authors = cleaner.clean_byline(
        byline=raw_byline,
        source_name=source_name,
        return_json=False
    )
    
    # Convert to JSON for storage
    new_author_json = json.dumps(cleaned_authors) if cleaned_authors else None
    
    # Parse current authors for comparison
    current_author = article_data['current_author']
    try:
        if current_author.startswith('['):
            current_authors = json.loads(current_author)
        else:
            current_authors = [current_author] if current_author else []
    except (json.JSONDecodeError, AttributeError):
        current_authors = [current_author] if current_author else []
    
    # Check if this is an improvement
    changed = current_authors != cleaned_authors
    improvement = False
    details = []
    
    if changed:
        # Check for name completions (truncation fixes)
        for old_name in current_authors:
            for new_name in cleaned_authors:
                if (old_name and new_name and 
                    old_name in new_name and len(new_name) > len(old_name)):
                    improvement = True
                    details.append(f"Fixed: '{old_name}' -> '{new_name}'")
        
        # Check for "Associated Press" fix
        if ('Associated' in str(current_authors) and 
            'Associated Press' in str(cleaned_authors)):
            improvement = True
            details.append("Fixed 'Associated Press' truncation")
    
    return {
        'new_author_json': new_author_json,
        'changed': changed,
        'improvement': improvement,
        'details': details,
        'old_authors': current_authors,
        'new_authors': cleaned_authors
    }


def update_article_author(db_path, article_id, new_author_json, dry_run=False):
    """Update the author field for an article."""
    if dry_run:
        return True
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            UPDATE articles 
            SET author = ?, processed_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (new_author_json, article_id))
        return conn.total_changes > 0


def main():
    """Main processing function."""
    parser = argparse.ArgumentParser(
        description="Re-clean article author names"
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Show changes without updating database')
    parser.add_argument('--limit', type=int,
                       help='Only process N articles')
    parser.add_argument('--db-path', default='data/mizzou.db',
                       help='Database file path')
    
    args = parser.parse_args()
    
    # Setup
    logger = setup_logging()
    cleaner = BylineCleaner(enable_telemetry=False)
    
    # Create backup unless dry run
    if not args.dry_run:
        backup_id = create_backup(args.db_path, logger)
        logger.info(f"Backup created: {backup_id}")
    else:
        logger.info("DRY RUN MODE - No changes will be made")
    
    # Get articles to process
    articles = get_articles_to_reclean(args.db_path, args.limit)
    logger.info(f"Found {len(articles)} articles to process")
    
    if not articles:
        logger.info("No articles found to process")
        return
    
    # Process articles
    stats = {
        'total': 0,
        'changed': 0,
        'improvements': 0,
        'errors': 0
    }
    
    changes_log = []
    
    for i, article_data in enumerate(articles, 1):
        article_id = article_data['article_id']
        
        if i % 50 == 0:
            logger.info(f"Processing {i}/{len(articles)}: {article_id}")
        
        try:
            # Clean the byline
            result = clean_author_byline(cleaner, article_data)
            stats['total'] += 1
            
            if result['changed'] and result['new_author_json']:
                # Update database
                success = update_article_author(
                    args.db_path, article_id, 
                    result['new_author_json'], args.dry_run
                )
                
                if success:
                    stats['changed'] += 1
                    if result['improvement']:
                        stats['improvements'] += 1
                        logger.info(f"IMPROVEMENT {article_id}: "
                                  f"{' | '.join(result['details'])}")
                    
                    # Log change
                    changes_log.append({
                        'article_id': article_id,
                        'raw_byline': article_data['raw_byline'],
                        'old_authors': result['old_authors'],
                        'new_authors': result['new_authors'],
                        'improvement': result['improvement'],
                        'details': result['details']
                    })
                else:
                    stats['errors'] += 1
                    logger.error(f"Failed to update article {article_id}")
            
        except Exception as e:
            stats['errors'] += 1
            logger.error(f"Error processing {article_id}: {e}")
    
    # Save changes log
    if changes_log:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        changes_file = f"data/author_changes_{timestamp}.json"
        with open(changes_file, 'w') as f:
            json.dump(changes_log, f, indent=2)
        logger.info(f"Changes saved to: {changes_file}")
    
    # Report stats
    logger.info("=" * 50)
    logger.info("FINAL STATISTICS")
    logger.info(f"Total processed: {stats['total']}")
    logger.info(f"Articles changed: {stats['changed']}")
    logger.info(f"Improvements: {stats['improvements']}")
    logger.info(f"Errors: {stats['errors']}")
    
    if stats['total'] > 0:
        change_rate = (stats['changed'] / stats['total']) * 100
        improvement_rate = (stats['improvements'] / stats['total']) * 100
        logger.info(f"Change rate: {change_rate:.1f}%")
        logger.info(f"Improvement rate: {improvement_rate:.1f}%")
    
    logger.info("=" * 50)


if __name__ == '__main__':
    main()