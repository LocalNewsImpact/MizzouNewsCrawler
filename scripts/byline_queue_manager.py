#!/usr/bin/env python3
"""
Queue-based byline cleaning system.

This approach uses a simple queue table to track articles that need
byline cleaning, allowing for distributed processing and better error handling.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from src.utils.byline_cleaner import BylineCleaner
from sqlalchemy import text

logger = logging.getLogger(__name__)


class BylineCleaningQueue:
    """Queue-based system for managing byline cleaning tasks."""
    
    def __init__(self):
        """Initialize the queue system."""
        self.db = DatabaseManager()
        self.cleaner = BylineCleaner()
        self._ensure_queue_table()
    
    def _ensure_queue_table(self):
        """Create the byline cleaning queue table if it doesn't exist."""
        session = self.db.session
        
        try:
            # Create queue table for tracking cleaning tasks
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS byline_cleaning_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id TEXT NOT NULL,
                    raw_author TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP NULL,
                    error_message TEXT NULL,
                    retry_count INTEGER DEFAULT 0,
                    FOREIGN KEY (article_id) REFERENCES articles(id)
                )
            """))
            
            # Create index for efficient processing
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_byline_queue_status 
                ON byline_cleaning_queue(status, created_at)
            """))
            
            session.commit()
            logger.debug("Byline cleaning queue table ready")
            
        except Exception as e:
            logger.error(f"Error setting up queue table: {e}")
            session.rollback()
        finally:
            session.close()
    
    def add_article_to_queue(self, article_id: str, raw_author: str) -> bool:
        """
        Add an article to the byline cleaning queue.
        
        Args:
            article_id: Article ID needing cleaning
            raw_author: Raw author string to clean
            
        Returns:
            True if successfully added to queue
        """
        session = self.db.session
        
        try:
            # Check if already in queue
            existing = session.execute(
                text("""
                    SELECT id FROM byline_cleaning_queue 
                    WHERE article_id = :article_id 
                    AND status IN ('pending', 'processing')
                """),
                {"article_id": article_id}
            ).fetchone()
            
            if existing:
                logger.debug(f"Article {article_id} already in queue")
                return False
            
            # Add to queue
            session.execute(
                text("""
                    INSERT INTO byline_cleaning_queue 
                    (article_id, raw_author, status, created_at)
                    VALUES (:article_id, :raw_author, 'pending', :created_at)
                """),
                {
                    "article_id": article_id,
                    "raw_author": raw_author,
                    "created_at": datetime.utcnow().isoformat()
                }
            )
            session.commit()
            
            logger.debug(f"Added article {article_id} to cleaning queue")
            return True
            
        except Exception as e:
            logger.error(f"Error adding article to queue: {e}")
            session.rollback()
            return False
        finally:
            session.close()
    
    def process_queue_batch(self, batch_size: int = 10) -> int:
        """
        Process a batch of items from the cleaning queue.
        
        Args:
            batch_size: Number of items to process in this batch
            
        Returns:
            Number of items successfully processed
        """
        session = self.db.session
        processed_count = 0
        
        try:
            # Get pending items from queue
            pending_items = session.execute(
                text("""
                    SELECT id, article_id, raw_author 
                    FROM byline_cleaning_queue 
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT :batch_size
                """),
                {"batch_size": batch_size}
            ).fetchall()
            
            if not pending_items:
                logger.debug("No pending items in byline cleaning queue")
                return 0
            
            logger.info(f"Processing {len(pending_items)} byline cleaning tasks")
            
            for queue_id, article_id, raw_author in pending_items:
                success = self._process_single_item(
                    session, queue_id, article_id, raw_author
                )
                if success:
                    processed_count += 1
            
            session.commit()
            logger.info(f"Processed {processed_count}/{len(pending_items)} items")
            
        except Exception as e:
            logger.error(f"Error processing queue batch: {e}")
            session.rollback()
        finally:
            session.close()
            
        return processed_count
    
    def _process_single_item(self, session, queue_id: int, 
                           article_id: str, raw_author: str) -> bool:
        """Process a single item from the queue."""
        try:
            # Mark as processing
            session.execute(
                text("""
                    UPDATE byline_cleaning_queue 
                    SET status = 'processing' 
                    WHERE id = :queue_id
                """),
                {"queue_id": queue_id}
            )
            
            # Clean the author field
            cleaned_author = self.cleaner.clean_byline(raw_author)
            
            # Update the article if cleaning changed something
            if cleaned_author != raw_author:
                session.execute(
                    text("""
                        UPDATE articles 
                        SET author = :cleaned_author,
                            updated_at = :updated_at
                        WHERE id = :article_id
                    """),
                    {
                        "cleaned_author": cleaned_author,
                        "updated_at": datetime.utcnow().isoformat(),
                        "article_id": article_id
                    }
                )
                
                logger.info(f"Cleaned author for {article_id[:8]}...: "
                           f"'{raw_author}' → '{cleaned_author}'")
            
            # Mark as completed
            session.execute(
                text("""
                    UPDATE byline_cleaning_queue 
                    SET status = 'completed',
                        processed_at = :processed_at
                    WHERE id = :queue_id
                """),
                {
                    "processed_at": datetime.utcnow().isoformat(),
                    "queue_id": queue_id
                }
            )
            
            return True
            
        except Exception as e:
            # Mark as failed and increment retry count
            session.execute(
                text("""
                    UPDATE byline_cleaning_queue 
                    SET status = 'failed',
                        error_message = :error,
                        retry_count = retry_count + 1,
                        processed_at = :processed_at
                    WHERE id = :queue_id
                """),
                {
                    "error": str(e),
                    "processed_at": datetime.utcnow().isoformat(),
                    "queue_id": queue_id
                }
            )
            
            logger.error(f"Failed to process queue item {queue_id}: {e}")
            return False
    
    def get_queue_status(self) -> dict:
        """Get current queue status."""
        session = self.db.session
        
        try:
            status = session.execute(text("""
                SELECT 
                    status,
                    COUNT(*) as count
                FROM byline_cleaning_queue 
                GROUP BY status
            """)).fetchall()
            
            return {row[0]: row[1] for row in status}
            
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return {}
        finally:
            session.close()
    
    def cleanup_old_completed(self, days: int = 7) -> int:
        """Clean up old completed queue items."""
        session = self.db.session
        
        try:
            result = session.execute(
                text("""
                    DELETE FROM byline_cleaning_queue 
                    WHERE status = 'completed' 
                    AND processed_at < datetime('now', '-{} days')
                """.format(days))
            )
            
            deleted_count = result.rowcount
            session.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old queue items")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up queue: {e}")
            session.rollback()
            return 0
        finally:
            session.close()


def auto_queue_new_articles():
    """
    Automatically add new articles with raw author data to the cleaning queue.
    This can be called periodically or triggered by the extraction process.
    """
    queue = BylineCleaningQueue()
    db = DatabaseManager()
    session = db.session
    
    try:
        # Find articles with raw author data that haven't been queued
        articles = session.execute(text("""
            SELECT a.id, a.author 
            FROM articles a
            LEFT JOIN byline_cleaning_queue q ON a.id = q.article_id
            WHERE a.author IS NOT NULL 
            AND a.author != ''
            AND q.article_id IS NULL
            AND (
                a.author LIKE '%Staff%' OR
                a.author LIKE '%Editor%' OR  
                a.author LIKE '%Reporter%' OR
                a.author LIKE '%@%' OR
                a.author LIKE '%,%' OR
                a.author = UPPER(a.author) OR
                a.author LIKE 'By %'
            )
            LIMIT 100
        """)).fetchall()
        
        added_count = 0
        for article_id, raw_author in articles:
            if queue.add_article_to_queue(article_id, raw_author):
                added_count += 1
        
        if added_count > 0:
            logger.info(f"Added {added_count} articles to byline cleaning queue")
        
        return added_count
        
    except Exception as e:
        logger.error(f"Error auto-queueing articles: {e}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO)
    
    parser = argparse.ArgumentParser(description="Byline cleaning queue manager")
    parser.add_argument("action", choices=[
        "process", "status", "queue", "cleanup"
    ], help="Action to perform")
    parser.add_argument("--batch-size", type=int, default=10,
                       help="Batch size for processing")
    parser.add_argument("--cleanup-days", type=int, default=7,
                       help="Days to keep completed items")
    
    args = parser.parse_args()
    
    queue = BylineCleaningQueue()
    
    if args.action == "process":
        processed = queue.process_queue_batch(args.batch_size)
        print(f"Processed {processed} items")
        
    elif args.action == "status":
        status = queue.get_queue_status()
        print("Queue Status:")
        for state, count in status.items():
            print(f"  {state}: {count}")
            
    elif args.action == "queue":
        added = auto_queue_new_articles()
        print(f"Added {added} articles to queue")
        
    elif args.action == "cleanup":
        cleaned = queue.cleanup_old_completed(args.cleanup_days)
        print(f"Cleaned up {cleaned} old items")