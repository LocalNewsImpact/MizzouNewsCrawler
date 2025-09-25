#!/usr/bin/env python3
"""
Simple extraction script to continue processing candidate links.
Includes candidate status updates and minimal telemetry.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))

from src.models.database import DatabaseManager

# Simple logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_candidates_for_extraction(db, limit=10):
    """Get candidates with status 'discovered' for extraction."""
    with db.engine.connect() as conn:
        result = conn.execute(text(
            "SELECT id, url, source FROM candidate_links WHERE status = 'discovered' LIMIT :limit"
        ), {'limit': limit})
        return [dict(row._mapping) for row in result]


def update_candidate_status(db, candidate_id, status, publish_date=None, error_message=None):
    """Update candidate status after extraction attempt."""
    update_data = {
        'candidate_id': candidate_id,
        'status': status,
        'processed_at': datetime.now().isoformat()
    }
    
    set_clauses = ['status = :status', 'processed_at = :processed_at']
    
    if publish_date:
        set_clauses.append('publish_date = :publish_date')
        update_data['publish_date'] = publish_date
        
    if error_message:
        set_clauses.append('error_message = :error_message')
        update_data['error_message'] = error_message
    
    update_query = f"""
        UPDATE candidate_links 
        SET {', '.join(set_clauses)}
        WHERE id = :candidate_id
    """
    
    with db.engine.connect() as conn:
        conn.execute(text(update_query), update_data)
        conn.commit()


def simple_extract_content(url):
    """Simple content extraction using newspaper3k."""
    try:
        import newspaper
        article = newspaper.Article(url)
        article.download()
        article.parse()
        
        if article.title and article.text:
            return {
                'title': article.title,
                'content': article.text,
                'author': ', '.join(article.authors) if article.authors else '',
                'publish_date': article.publish_date.isoformat() if article.publish_date else '',
                'success': True
            }
        else:
            return {'success': False, 'error': 'No title or content extracted'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_article_record(db, candidate, extraction_result):
    """Create article record from extraction result."""
    article_data = {
        'id': f"art_{candidate['id'][:8]}_{int(datetime.now().timestamp())}",
        'title': extraction_result.get('title', ''),
        'content': extraction_result.get('content', ''),
        'url': candidate['url'],
        'source': candidate['source'],
        'author': extraction_result.get('author', ''),
        'publish_date': extraction_result.get('publish_date', ''),
        'scraped_at': datetime.now().isoformat(),
        'candidate_link_id': candidate['id'],
        'success': extraction_result['success'],
        'word_count': len(extraction_result.get('content', '').split()) if extraction_result.get('content') else 0
    }
    
    # Insert into articles table (assuming it exists)
    columns = ', '.join(article_data.keys())
    placeholders = ', '.join([f":{k}" for k in article_data.keys()])
    
    with db.engine.connect() as conn:
        conn.execute(text(f"""
            INSERT INTO articles ({columns}) 
            VALUES ({placeholders})
        """), article_data)
        conn.commit()
    
    return article_data


def main():
    """Main extraction function."""
    db = DatabaseManager()
    
    # Get candidates for extraction
    candidates = get_candidates_for_extraction(db, limit=5)  # Small batch
    logger.info(f"Found {len(candidates)} candidates for extraction")
    
    if not candidates:
        logger.info("No candidates found with 'discovered' status")
        return
    
    successful = 0
    failed = 0
    
    for i, candidate in enumerate(candidates, 1):
        logger.info(f"[{i}/{len(candidates)}] Processing: {candidate['url']}")
        
        try:
            # Extract content
            extraction_result = simple_extract_content(candidate['url'])
            
            if extraction_result['success']:
                # Create article record
                article = create_article_record(db, candidate, extraction_result)
                
                # Update candidate status to 'extracted'
                update_candidate_status(
                    db, 
                    candidate['id'], 
                    'extracted',
                    publish_date=extraction_result.get('publish_date')
                )
                
                successful += 1
                logger.info(f"✓ Successfully extracted: {article['title'][:60]}...")
            else:
                # Update candidate status to 'failed'
                update_candidate_status(
                    db, 
                    candidate['id'], 
                    'failed',
                    error_message=extraction_result['error']
                )
                
                failed += 1
                logger.warning(f"✗ Extraction failed: {extraction_result['error']}")
                
        except Exception as e:
            # Update candidate status to 'failed'
            update_candidate_status(
                db, 
                candidate['id'], 
                'failed',
                error_message=str(e)
            )
            
            failed += 1
            logger.error(f"✗ Unexpected error: {e}")
    
    # Summary
    logger.info(f"\nExtraction completed:")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Total: {len(candidates)}")
    logger.info(f"  Success rate: {(successful / len(candidates) * 100):.1f}%")
    
    # Check updated status distribution
    with db.engine.connect() as conn:
        result = conn.execute(text(
            "SELECT status, COUNT(*) as count FROM candidate_links GROUP BY status ORDER BY count DESC"
        ))
        status_counts = [dict(row._mapping) for row in result]
    
    logger.info("\nUpdated status distribution:")
    for status in status_counts:
        logger.info(f"  {status['status']}: {status['count']}")


if __name__ == "__main__":
    main()