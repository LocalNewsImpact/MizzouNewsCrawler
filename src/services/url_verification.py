#!/usr/bin/env python3
"""
URL Verification Service using StorySniffer.

This service processes URLs with 'discovered' status and verifies them
using StorySniffer to determine if they are articles or not.
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import text

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import after path modification
try:
    import storysniffer
except ImportError:
    print("Error: storysniffer not installed. Run: pip install storysniffer")
    sys.exit(1)

from src.models.database import DatabaseManager


class URLVerificationService:
    """Service to verify URLs with StorySniffer and update their status."""

    def __init__(self, batch_size: int = 100, sleep_interval: int = 30):
        """Initialize the verification service.

        Args:
            batch_size: Number of URLs to process in each batch
            sleep_interval: Seconds to wait between batches when no work
        """
        self.batch_size = batch_size
        self.sleep_interval = sleep_interval
        self.db = DatabaseManager()
        self.sniffer = storysniffer.StorySniffer()
        self.logger = logging.getLogger(__name__)
        self.running = False

    def get_unverified_urls(self, limit: Optional[int] = None) -> List[Dict]:
        """Get candidate links that need verification."""
        query = """
            SELECT id, url, source_name, source_city, source_county, status
            FROM candidate_links
            WHERE status = 'discovered'
            ORDER BY created_at ASC
        """

        if limit:
            query += f" LIMIT {limit}"

        with self.db.engine.connect() as conn:
            result = conn.execute(text(query))
            return [dict(row._mapping) for row in result.fetchall()]

    def verify_url(self, url: str) -> Dict:
        """Verify a single URL with StorySniffer.

        Returns:
            Dict with verification results and timing info
        """
        start_time = time.time()
        result = {
            'url': url,
            'storysniffer_result': None,
            'verification_time_ms': 0,
            'error': None,
        }

        try:
            # Run StorySniffer verification
            is_article = self.sniffer.guess(url)
            result['storysniffer_result'] = bool(is_article)
            result['verification_time_ms'] = (time.time() - start_time) * 1000

            self.logger.debug(
                f"Verified {url}: "
                f"{'article' if is_article else 'not_article'} "
                f"({result['verification_time_ms']:.1f}ms)"
            )

        except Exception as e:
            result['error'] = str(e)
            result['verification_time_ms'] = (time.time() - start_time) * 1000
            self.logger.warning(f"Verification failed for {url}: {e}")

        return result

    def update_candidate_status(
        self,
        candidate_id: str,
        new_status: str,
        error_message: Optional[str] = None
    ):
        """Update candidate_links status based on verification."""
        update_data = {
            'candidate_id': candidate_id,
            'status': new_status,
            'processed_at': datetime.now(),
        }

        if error_message:
            update_data['error_message'] = error_message

        update_query = """
            UPDATE candidate_links
            SET status = :status, processed_at = :processed_at
        """

        if error_message:
            update_query += ", error_message = :error_message"

        update_query += " WHERE id = :candidate_id"

        with self.db.engine.connect() as conn:
            conn.execute(text(update_query), update_data)
            conn.commit()

        self.logger.debug(f"Updated candidate {candidate_id} to: {new_status}")

    def process_batch(self, candidates: List[Dict]) -> Dict:
        """Process a batch of candidates and return metrics."""
        batch_metrics: Dict = {
            'total_processed': 0,
            'verified_articles': 0,
            'verified_non_articles': 0,
            'verification_errors': 0,
            'total_time_ms': 0.0,
            'batch_time_seconds': 0.0,
            'avg_verification_time_ms': 0.0,
        }

        batch_start_time = time.time()

        for candidate in candidates:
            # Verify URL
            verification_result = self.verify_url(candidate['url'])
            batch_metrics['total_processed'] += 1

            # Determine new status and update metrics
            if verification_result.get('error'):
                batch_metrics['verification_errors'] += 1
                new_status = 'verification_failed'
                error_message = verification_result['error']
            elif verification_result.get('storysniffer_result'):
                batch_metrics['verified_articles'] += 1
                new_status = 'article'
                error_message = None
            else:
                batch_metrics['verified_non_articles'] += 1
                new_status = 'not_article'
                error_message = None

            batch_metrics['total_time_ms'] += verification_result.get(
                'verification_time_ms', 0
            )

            # Update candidate status
            self.update_candidate_status(
                candidate['id'], new_status, error_message
            )

        # Calculate batch timing
        batch_metrics['batch_time_seconds'] = time.time() - batch_start_time
        batch_metrics['avg_verification_time_ms'] = (
            batch_metrics['total_time_ms'] / batch_metrics['total_processed']
            if batch_metrics['total_processed'] > 0
            else 0.0
        )

        return batch_metrics

    def save_telemetry_summary(
        self, batch_metrics: Dict, candidates: List[Dict], job_name: str
    ):
        """Save telemetry summary to a simple log file."""
        summary = {
            'timestamp': datetime.now().isoformat(),
            'job_name': job_name,
            'batch_size': len(candidates),
            'metrics': batch_metrics,
            'sources_processed': list(
                set(c.get('source_name', 'Unknown') for c in candidates)
            ),
        }

        # Write to telemetry log file
        log_file = Path('verification_telemetry.log')
        with open(log_file, 'a') as f:
            f.write(f"{summary}\n")

        self.logger.info(f"Telemetry saved to {log_file}")

    def run_verification_loop(self, max_batches: Optional[int] = None):
        """Run the main verification loop."""
        self.running = True
        batch_count = 0
        job_name = f"verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.logger.info(
            f"Starting verification loop: {job_name} "
            f"(batch_size={self.batch_size}, "
            f"sleep_interval={self.sleep_interval}s)"
        )

        try:
            while self.running:
                # Get unverified URLs
                candidates = self.get_unverified_urls(self.batch_size)

                if not candidates:
                    self.logger.info(
                        "No URLs to verify, sleeping for "
                        f"{self.sleep_interval} seconds..."
                    )
                    time.sleep(self.sleep_interval)
                    continue

                self.logger.info(
                    f"Processing batch {batch_count + 1} "
                    f"of {len(candidates)} URLs..."
                )

                # Process batch
                batch_metrics = self.process_batch(candidates)

                # Save telemetry
                self.save_telemetry_summary(
                    batch_metrics, candidates, job_name
                )

                # Log progress
                self.logger.info(
                    f"Batch complete: "
                    f"{batch_metrics['verified_articles']} articles, "
                    f"{batch_metrics['verified_non_articles']} non-articles, "
                    f"{batch_metrics['verification_errors']} errors "
                    f"(avg: {batch_metrics['avg_verification_time_ms']:.1f}ms)"
                )

                batch_count += 1
                if max_batches and batch_count >= max_batches:
                    self.logger.info(f"Reached max batches: {max_batches}")
                    break

                # Brief pause between batches
                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, stopping...")
        except Exception as e:
            self.logger.error(f"Verification loop failed: {e}")
            raise
        finally:
            self.running = False
            self.logger.info(f"Verification job completed: {job_name}")

    def stop(self):
        """Stop the verification service gracefully."""
        self.logger.info("Stopping verification service...")
        self.running = False

    def get_status_summary(self) -> Dict:
        """Get current status summary from the database."""
        query = """
            SELECT status, COUNT(*) as count
            FROM candidate_links
            GROUP BY status
            ORDER BY count DESC
        """

        with self.db.engine.connect() as conn:
            result = conn.execute(text(query))
            status_counts = {row[0]: row[1] for row in result.fetchall()}

        return {
            'total_urls': sum(status_counts.values()),
            'status_breakdown': status_counts,
            'verification_pending': status_counts.get('discovered', 0),
            'articles_verified': status_counts.get('article', 0),
            'non_articles_verified': status_counts.get('not_article', 0),
            'verification_failures': status_counts.get(
                'verification_failed', 0
            ),
        }


def setup_logging(level: str = "INFO"):
    """Configure logging for the verification service."""
    log_level = getattr(logging, level.upper())
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('verification_service.log'),
        ],
    )


def main():
    """Main entry point for the verification service."""
    parser = argparse.ArgumentParser(
        description='URL verification service with StorySniffer'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of URLs to process per batch (default: 100)',
    )
    parser.add_argument(
        '--sleep-interval',
        type=int,
        default=30,
        help='Seconds to sleep when no work available (default: 30)',
    )
    parser.add_argument(
        '--max-batches',
        type=int,
        help='Maximum number of batches to process (default: unlimited)',
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)',
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current verification status and exit',
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    # Create verification service
    service = URLVerificationService(
        batch_size=args.batch_size, sleep_interval=args.sleep_interval
    )

    try:
        if args.status:
            # Show status summary
            status = service.get_status_summary()
            print("\nURL Verification Status:")
            print("=" * 40)
            print(f"Total URLs: {status['total_urls']}")
            print(f"Pending verification: {status['verification_pending']}")
            print(f"Verified articles: {status['articles_verified']}")
            print(f"Verified non-articles: {status['non_articles_verified']}")
            print(f"Verification failures: {status['verification_failures']}")
            print("\nStatus breakdown:")
            for status_name, count in status['status_breakdown'].items():
                print(f"  {status_name}: {count}")
            return 0

        logger.info("Starting URL verification service")

        # Run verification loop
        service.run_verification_loop(max_batches=args.max_batches)

        logger.info("Verification service completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Verification service failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
