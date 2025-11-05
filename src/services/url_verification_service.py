#!/usr/bin/env python3
"""
Background URL verification service using StorySniffer.

This service continuously monitors candidate_links with 'discovered' status
and runs StorySniffer verification to classify them as 'article' or
'not_article'. Includes comprehensive telemetry tracking and error handling.
"""

import argparse
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

import storysniffer  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.models.database import (  # noqa: E402
    DatabaseManager,
    safe_execute,
    safe_session_execute,
)
from src.models.verification import (  # noqa: E402
    URLVerification,
    VerificationJob,
    VerificationTelemetry,
)


class URLVerificationService:
    """Background service for verifying URLs with StorySniffer."""

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
        self.current_job: VerificationJob | None = None
        self.running = False

    def start_verification_job(
        self,
        job_name: str,
        discovery_job_id: str | None = None,
        config: dict | None = None,
    ) -> str:
        """Start a new verification job."""
        job_id = str(uuid.uuid4())

        job = VerificationJob(
            id=job_id,
            job_name=job_name,
            discovery_job_id=discovery_job_id,
            status="running",
            config=config or {},
        )

        # Use the existing session from DatabaseManager
        session = self.db.session
        session.add(job)
        session.commit()
        self.current_job = job

        self.logger.info(f"Started verification job: {job_name} ({job_id})")
        return job_id

    def get_unverified_urls(self, limit: int = None) -> list[dict]:
        """Get candidate links that need verification."""
        query = """
            SELECT id, url, source_name, source_city, source_county,
                   discovered_by, status
            FROM candidate_links
            WHERE status = 'discovered'
            ORDER BY created_at ASC
        """

        if limit:
            query += f" LIMIT {limit}"

        with self.db.engine.connect() as conn:
            result = safe_execute(conn, query)
            return [dict(row._mapping) for row in result.fetchall()]

    def verify_url(self, url: str) -> dict:
        """Verify a single URL with StorySniffer.

        Returns:
            Dict with verification results and timing info
        """
        start_time = time.time()
        result = {
            "url": url,
            "storysniffer_result": None,
            "verification_time_ms": 0.0,
            "error": None,
        }

        try:
            # Run StorySniffer verification
            is_article = self.sniffer.guess(url)
            result["storysniffer_result"] = bool(is_article)
            result["verification_time_ms"] = (time.time() - start_time) * 1000

            self.logger.debug(
                f"Verified {url}: {'article' if is_article else 'not_article'} "
                f"({result['verification_time_ms']:.1f}ms)"
            )

        except Exception as e:
            result["error"] = str(e)
            result["verification_time_ms"] = (time.time() - start_time) * 1000
            self.logger.warning(f"Verification failed for {url}: {e}")

        return result

    def update_candidate_status(
        self, candidate_id: str, new_status: str, verification_result: dict
    ):
        """Update candidate_links status based on verification."""
        update_query = """
            UPDATE candidate_links
            SET status = :status, processed_at = :processed_at
            WHERE id = :candidate_id
        """

        with self.db.engine.connect() as conn:
            safe_execute(
                conn,
                update_query,
                {
                    "candidate_id": candidate_id,
                    "status": new_status,
                    "processed_at": datetime.now(),
                },
            )
            try:
                conn.commit()
            except Exception:
                pass

        self.logger.debug(f"Updated candidate {candidate_id} to status: {new_status}")

    def save_verification_result(
        self, candidate: dict, verification_result: dict
    ) -> URLVerification:
        """Save individual verification result to database."""
        verification = URLVerification(
            candidate_link_id=candidate["id"],
            verification_job_id=self.current_job.id,
            url=candidate["url"],
            storysniffer_result=verification_result.get("storysniffer_result"),
            verification_time_ms=verification_result.get("verification_time_ms"),
            previous_status=candidate["status"],
            new_status=(
                "article"
                if verification_result.get("storysniffer_result")
                else "not_article"
            ),
            verification_error=verification_result.get("error"),
        )

        # Use the existing session from DatabaseManager
        session = self.db.session
        session.add(verification)
        session.commit()

        return verification

    def process_batch(self, candidates: list[dict]) -> dict:
        """Process a batch of candidates and return metrics."""
        batch_metrics: dict[str, Any] = {
            "total_processed": 0,
            "verified_articles": 0,
            "verified_non_articles": 0,
            "verification_errors": 0,
            "total_time_ms": 0.0,
        }

        batch_start_time = time.time()

        for candidate in candidates:
            # Verify URL
            verification_result = self.verify_url(candidate["url"])
            batch_metrics["total_processed"] += 1

            # Update metrics
            if verification_result.get("error"):
                batch_metrics["verification_errors"] += 1
                new_status = "verification_failed"
            elif verification_result.get("storysniffer_result"):
                batch_metrics["verified_articles"] += 1
                new_status = "article"
            else:
                batch_metrics["verified_non_articles"] += 1
                new_status = "not_article"

            batch_metrics["total_time_ms"] += verification_result.get(
                "verification_time_ms", 0
            )

            # Update candidate status
            self.update_candidate_status(
                candidate["id"], new_status, verification_result
            )

            # Save verification result
            self.save_verification_result(candidate, verification_result)

        # Calculate batch timing
        batch_metrics["batch_time_seconds"] = time.time() - batch_start_time
        batch_metrics["avg_verification_time_ms"] = (
            batch_metrics["total_time_ms"] / batch_metrics["total_processed"]
            if batch_metrics["total_processed"] > 0
            else 0
        )

        return batch_metrics

    def update_job_metrics(self, batch_metrics: dict):
        """Update job-level metrics with batch results."""
        if not self.current_job:
            return

        update_query = """
            UPDATE verification_jobs
            SET processed_urls = processed_urls + :processed,
                verified_articles = verified_articles + :articles,
                verified_non_articles = verified_non_articles + :non_articles,
                verification_errors = verification_errors + :errors,
                total_processing_time_seconds = COALESCE(total_processing_time_seconds, 0) + :batch_time
            WHERE id = :job_id
        """

        with self.db.engine.connect() as conn:
            safe_execute(
                conn,
                update_query,
                {
                    "job_id": self.current_job.id,
                    "processed": batch_metrics["total_processed"],
                    "articles": batch_metrics["verified_articles"],
                    "non_articles": batch_metrics["verified_non_articles"],
                    "errors": batch_metrics["verification_errors"],
                    "batch_time": batch_metrics["batch_time_seconds"],
                },
            )
            try:
                conn.commit()
            except Exception:
                pass

    def generate_telemetry(self, batch_metrics: dict, candidates: list[dict]):
        """Generate telemetry data for this batch."""
        # Group candidates by source for telemetry
        source_metrics: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            source_name = candidate.get("source_name", "Unknown")
            if source_name not in source_metrics:
                source_metrics[source_name] = {
                    "total_urls": 0,
                    "verified_articles": 0,
                    "verified_non_articles": 0,
                    "verification_errors": 0,
                    "source_county": candidate.get("source_county"),
                }

            source_metrics[source_name]["total_urls"] += 1

        # Update source metrics based on verification results
        # Use existing session from DatabaseManager
        session = self.db.session

        # Get verification results for this batch
        # Use Python datetime for cross-database compatibility
        from datetime import timedelta

        cutoff_time = datetime.now() - timedelta(minutes=1)

        verification_query = text(
            """
            SELECT v.url, v.storysniffer_result, v.verification_error, cl.source_name
            FROM url_verifications v
            JOIN candidate_links cl ON v.candidate_link_id = cl.id
            WHERE v.verification_job_id = :job_id
            AND v.verified_at >= :cutoff_time
        """
        )

        results = safe_session_execute(
            session,
            verification_query,
            {"job_id": self.current_job.id, "cutoff_time": cutoff_time},
        ).fetchall()

        for result in results:
            source_name = result.source_name
            if source_name in source_metrics:
                if result.verification_error:
                    source_metrics[source_name]["verification_errors"] += 1
                elif result.storysniffer_result:
                    source_metrics[source_name]["verified_articles"] += 1
                else:
                    source_metrics[source_name]["verified_non_articles"] += 1

        # Save telemetry records
        for source_name, metrics in source_metrics.items():
            if metrics["total_urls"] > 0:
                article_rate = (
                    metrics["verified_articles"] / metrics["total_urls"] * 100
                    if metrics["total_urls"] > 0
                    else 0
                )

                telemetry = VerificationTelemetry(
                    verification_job_id=self.current_job.id,
                    source_name=source_name,
                    source_county=metrics["source_county"],
                    total_urls=metrics["total_urls"],
                    verified_articles=metrics["verified_articles"],
                    verified_non_articles=metrics["verified_non_articles"],
                    verification_errors=metrics["verification_errors"],
                    article_rate=article_rate,
                    avg_verification_time_ms=batch_metrics.get(
                        "avg_verification_time_ms", 0
                    ),
                )
                session.add(telemetry)

        session.commit()

    def run_verification_loop(
        self,
        *,
        max_batches: int | None = None,
        exit_on_idle: bool = False,
    ) -> None:
        """Run the main verification loop.

        Args:
            max_batches: Optional maximum number of batches to process.
            exit_on_idle: When True, stop polling once no URLs remain.
        """
        self.running = True
        batch_count = 0

        self.logger.info(
            f"Starting verification loop (batch_size={self.batch_size}, "
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
                    if exit_on_idle:
                        break
                    time.sleep(self.sleep_interval)
                    continue

                self.logger.info(f"Processing batch of {len(candidates)} URLs...")

                # Process batch
                batch_metrics = self.process_batch(candidates)

                # Update job metrics
                self.update_job_metrics(batch_metrics)

                # Generate telemetry
                self.generate_telemetry(batch_metrics, candidates)

                # Log progress
                self.logger.info(
                    f"Batch complete: {batch_metrics['verified_articles']} articles, "
                    f"{batch_metrics['verified_non_articles']} non-articles, "
                    f"{batch_metrics['verification_errors']} errors "
                    f"(avg: {batch_metrics['avg_verification_time_ms']:.1f}ms)"
                )

                batch_count += 1
                if max_batches and batch_count >= max_batches:
                    self.logger.info(f"Reached max batches limit: {max_batches}")
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
            self.finish_current_job()

    def finish_current_job(self):
        """Mark the current job as completed."""
        if not self.current_job:
            return

        # Get final totals
        with self.db.engine.connect() as conn:
            result = safe_execute(
                conn,
                text(
                    "SELECT COUNT(*) FROM candidate_links WHERE status = 'discovered'"
                ),
            ).fetchone()
            remaining_discovered = result[0] if result else 0

            # Update job status
            update_query = """
                UPDATE verification_jobs
                SET status = :status,
                    completed_at = :completed_at,
                    total_urls = (
                        SELECT COUNT(*) FROM url_verifications
                        WHERE verification_job_id = :job_id
                    )
                WHERE id = :job_id
            """

            safe_execute(
                conn,
                update_query,
                {
                    "job_id": self.current_job.id,
                    "status": "completed" if remaining_discovered == 0 else "paused",
                    "completed_at": datetime.now(),
                },
            )
            try:
                conn.commit()
            except Exception:
                pass

        self.logger.info(
            f"Finished verification job: {self.current_job.job_name} "
            f"({remaining_discovered} URLs remaining)"
        )
        self.current_job = None

    def stop(self):
        """Stop the verification service gracefully."""
        self.logger.info("Stopping verification service...")
        self.running = False


def setup_logging(level: str = "INFO"):
    """Configure logging for the verification service."""
    log_level = getattr(logging, level.upper())
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("verification_service.log"),
        ],
    )


def main():
    """Main entry point for the verification service."""
    parser = argparse.ArgumentParser(
        description="Background URL verification service with StorySniffer"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of URLs to process per batch (default: 100)",
    )
    parser.add_argument(
        "--sleep-interval",
        type=int,
        default=30,
        help="Seconds to sleep when no work available (default: 30)",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        help="Maximum number of batches to process (default: unlimited)",
    )
    parser.add_argument(
        "--job-name",
        default=f"verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Name for this verification job",
    )
    parser.add_argument(
        "--discovery-job-id",
        help="ID of the discovery job that found these URLs",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
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
        # Start verification job
        job_id = service.start_verification_job(
            job_name=args.job_name,
            discovery_job_id=args.discovery_job_id,
            config={
                "batch_size": args.batch_size,
                "sleep_interval": args.sleep_interval,
                "max_batches": args.max_batches,
            },
        )

        logger.info(f"Starting verification service with job ID: {job_id}")

        # Run verification loop
        service.run_verification_loop(
            max_batches=args.max_batches,
            exit_on_idle=True,
        )

        logger.info("Verification service completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Verification service failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
