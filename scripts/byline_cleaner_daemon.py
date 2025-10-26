#!/usr/bin/env python3
"""
Background worker for automatic byline cleaning.

This daemon monitors the articles table for new records and automatically
cleans author fields using the BylineCleaner.
"""

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text

from src.models.database import DatabaseManager
from src.utils.byline_cleaner import BylineCleaner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("byline_cleaner_daemon.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class BylineCleanerDaemon:
    """Background daemon for automatic byline cleaning."""

    def __init__(self, check_interval: int = 30):
        """
        Initialize the daemon.

        Args:
            check_interval: Seconds between database checks
        """
        self.check_interval = check_interval
        self.running = True
        self.db = DatabaseManager()
        self.cleaner = BylineCleaner()

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def find_uncleaned_articles(self):
        """Find articles with uncleaned author fields."""
        session = self.db.session

        try:
            # Look for articles with raw author data that needs cleaning
            # This could be articles with common patterns like:
            # - Contains ", Staff" or ", Editor" etc.
            # - All caps names
            # - Email addresses
            # - Obvious title patterns
            query = text("""
                SELECT id, author 
                FROM articles 
                WHERE author IS NOT NULL 
                AND author != ''
                AND (
                    author LIKE '%Staff%' OR
                    author LIKE '%Editor%' OR  
                    author LIKE '%Reporter%' OR
                    author LIKE '%@%' OR
                    author LIKE '%,%' OR
                    author = UPPER(author) OR
                    author LIKE 'By %' OR
                    author LIKE 'Written by %'
                )
                AND (
                    -- Only process articles that haven't been cleaned recently
                    extracted_at > datetime('now', '-1 hour') OR
                    author NOT IN (SELECT author FROM articles WHERE author IS NOT NULL GROUP BY author HAVING COUNT(*) > 5)
                )
                LIMIT 50
            """)

            result = session.execute(query)
            articles = result.fetchall()

            logger.debug(f"Found {len(articles)} articles needing author cleaning")
            return articles

        except Exception as e:
            logger.error(f"Error finding uncleaned articles: {e}")
            return []
        finally:
            session.close()

    def clean_article_author(self, article_id: str, raw_author: str) -> bool:
        """
        Clean the author field for a specific article.

        Args:
            article_id: Article ID to update
            raw_author: Raw author string to clean

        Returns:
            True if successful, False otherwise
        """
        session = self.db.session

        try:
            # Clean the author field
            cleaned_author = self.cleaner.clean_byline(raw_author)

            # Only update if cleaning actually changed something
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
                        "article_id": article_id,
                    },
                )
                session.commit()

                logger.info(
                    f"Cleaned author for article {article_id[:8]}...: "
                    f"'{raw_author}' → '{cleaned_author}'"
                )
                return True
            else:
                logger.debug(f"No cleaning needed for article {article_id[:8]}...")
                return False

        except Exception as e:
            logger.error(f"Error cleaning author for article {article_id}: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    def run_cleaning_cycle(self):
        """Run one cycle of byline cleaning."""
        logger.debug("Starting byline cleaning cycle...")

        # Find articles that need cleaning
        articles = self.find_uncleaned_articles()

        if not articles:
            logger.debug("No articles need byline cleaning")
            return 0

        cleaned_count = 0
        for article_id, raw_author in articles:
            if not self.running:
                break

            if self.clean_article_author(article_id, raw_author):
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} author fields in this cycle")

        return cleaned_count

    def run(self):
        """Main daemon loop."""
        logger.info("Starting byline cleaner daemon...")
        logger.info(f"Check interval: {self.check_interval} seconds")

        total_cleaned = 0
        cycles = 0

        while self.running:
            try:
                cycles += 1
                cycle_cleaned = self.run_cleaning_cycle()
                total_cleaned += cycle_cleaned

                if cycles % 20 == 0:  # Log status every 20 cycles
                    logger.info(
                        f"Status: {total_cleaned} total authors cleaned "
                        f"over {cycles} cycles"
                    )

                # Wait for next cycle
                time.sleep(self.check_interval)

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in daemon loop: {e}")
                time.sleep(self.check_interval)

        logger.info(f"Daemon stopped. Total authors cleaned: {total_cleaned}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Byline cleaner daemon")
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Check interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--once", action="store_true", help="Run once and exit (don't run as daemon)"
    )

    args = parser.parse_args()

    daemon = BylineCleanerDaemon(check_interval=args.interval)

    if args.once:
        logger.info("Running single cleaning cycle...")
        cleaned = daemon.run_cleaning_cycle()
        logger.info(f"Single cycle complete. Cleaned {cleaned} authors.")
    else:
        daemon.run()
