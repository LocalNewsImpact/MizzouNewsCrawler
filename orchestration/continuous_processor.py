#!/usr/bin/env python3
"""Continuous processor that monitors database and triggers pipeline steps.

This service runs continuously and:
1. Checks for candidate_links with status='discovered' → runs verification
2. Checks for candidate_links with status='article' → runs extraction
3. Checks for articles without analysis → runs ML analysis
4. Checks for articles without entities → runs gazetteer/entity extraction

Each step is executed with appropriate batching and error handling.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import text

from src.models.database import DatabaseManager

# Configuration from environment
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))  # seconds
VERIFICATION_BATCH_SIZE = int(os.getenv("VERIFICATION_BATCH_SIZE", "10"))
EXTRACTION_BATCH_SIZE = int(os.getenv("EXTRACTION_BATCH_SIZE", "20"))
ANALYSIS_BATCH_SIZE = int(os.getenv("ANALYSIS_BATCH_SIZE", "16"))
GAZETTEER_BATCH_SIZE = int(os.getenv("GAZETTEER_BATCH_SIZE", "50"))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_MODULE = "src.cli.cli_modular"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class WorkQueue:
    """Check database for pending work."""

    @staticmethod
    def get_counts() -> dict[str, int]:
        """Return counts of work items in each stage."""
        counts = {
            "verification_pending": 0,
            "extraction_pending": 0,
            "cleaning_pending": 0,
            "analysis_pending": 0,
            "entity_extraction_pending": 0,
        }

        with DatabaseManager() as db:
            # Count candidate_links needing verification
            result = db.session.execute(
                text("SELECT COUNT(*) FROM candidate_links WHERE status = 'discovered'")
            )
            counts["verification_pending"] = result.scalar() or 0

            # Count candidate_links ready for extraction
            result = db.session.execute(
                text("SELECT COUNT(*) FROM candidate_links WHERE status = 'article'")
            )
            counts["extraction_pending"] = result.scalar() or 0

            # Count articles needing cleaning (status = extracted)
            result = db.session.execute(
                text(
                    "SELECT COUNT(*) FROM articles "
                    "WHERE status = 'extracted' AND content IS NOT NULL"
                )
            )
            counts["cleaning_pending"] = result.scalar() or 0

            # Count articles without ML analysis (only 'cleaned' status is eligible)
            result = db.session.execute(
                text(
                    "SELECT COUNT(*) FROM articles "
                    "WHERE status = 'cleaned' AND primary_label IS NULL"
                )
            )
            counts["analysis_pending"] = result.scalar() or 0

            # Count articles without entity extraction
            result = db.session.execute(
                text(
                    "SELECT COUNT(*) FROM articles a "
                    "WHERE NOT EXISTS ("
                    "  SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id"
                    ") AND a.content IS NOT NULL"
                )
            )
            counts["entity_extraction_pending"] = result.scalar() or 0

        return counts


def run_cli_command(command: list[str], description: str) -> bool:
    """Execute a CLI command, streaming output to logs in real-time.
    
    Returns True if successful. This improves observability in Kubernetes
    by emitting child process output directly to the pod logs instead of
    buffering it. We also log elapsed time.
    """
    logger.info("▶️  %s", description)
    cmd = [sys.executable, "-m", CLI_MODULE, *command]
    logger.info("🧰 Running: %s", " ".join(cmd))

    env = os.environ.copy()
    # Ensure unbuffered child output so we see logs in real time
    env.setdefault("PYTHONUNBUFFERED", "1")

    start = time.time()
    try:
        # Use Popen with real-time streaming for better observability
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )

        # Stream output line by line in real-time
        if proc.stdout:
            for line in iter(proc.stdout.readline, ''):
                if line:
                    logger.info("%s | %s", description, line.rstrip())
        
        # Wait for process to complete
        returncode = proc.wait()

        elapsed = time.time() - start
        if returncode == 0:
            logger.info("✅ %s completed successfully (%.1fs)", description, elapsed)
            return True
        else:
            logger.error(
                "❌ %s failed with exit code %d (%.1fs)",
                description,
                returncode,
                elapsed,
            )
            return False

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        logger.error("❌ %s timed out after %.1fs", description, elapsed)
        return False
    except Exception as exc:
        elapsed = time.time() - start
        logger.exception(
            "💥 %s raised exception after %.1fs: %s", description, elapsed, exc
        )
        return False


def process_verification(count: int) -> bool:
    """Run URL verification for discovered links."""
    if count == 0:
        return False

    batches_needed = (count + VERIFICATION_BATCH_SIZE - 1) // VERIFICATION_BATCH_SIZE
    batches_to_run = min(batches_needed, 10)  # Max 10 batches per cycle

    command = [
        "verify-urls",
        "--batch-size",
        str(VERIFICATION_BATCH_SIZE),
        "--max-batches",
        str(batches_to_run),
        "--sleep-interval",
        "5",
    ]

    return run_cli_command(
        command, f"URL verification ({count} pending, {batches_to_run} batches)"
    )


def process_extraction(count: int) -> bool:
    """Run article extraction for verified article links."""
    if count == 0:
        return False

    batches_needed = (count + EXTRACTION_BATCH_SIZE - 1) // EXTRACTION_BATCH_SIZE
    batches_to_run = min(5, batches_needed)

    command = [
        "extract",
        "--limit",
        str(EXTRACTION_BATCH_SIZE),
        "--batches",
        str(batches_to_run),
    ]

    return run_cli_command(
        command, f"Article extraction ({count} pending, {batches_to_run} batches)"
    )


def process_analysis(count: int) -> bool:
    """Run ML analysis for cleaned articles only."""
    if count == 0:
        return False

    limit = min(count, 100)  # Process up to 100 articles per cycle

    command = [
        "analyze",
        "--limit",
        str(limit),
        "--batch-size",
        str(ANALYSIS_BATCH_SIZE),
        "--top-k",
        "2",
        "--status",
        "cleaned",
    ]

    return run_cli_command(command, f"ML analysis ({count} pending, limit {limit})")


def process_cleaning(count: int) -> bool:
    """Run content cleaning for extracted articles."""
    if count == 0:
        return False

    limit = min(count, 100)  # Process up to 100 articles per cycle

    command = [
        "clean-articles",
        "--limit",
        str(limit),
        "--status",
        "extracted",
    ]

    return run_cli_command(
        command, f"Content cleaning ({count} pending, limit {limit})"
    )


def process_entity_extraction(count: int) -> bool:
    """Run entity extraction on articles that have content but no entities.

    This command extracts location entities from article text and stores
    them in the article_entities table. The gazetteer data (OSM locations
    for each source) should already be populated via the populate-gazetteer
    command during initial setup.
    """
    if count == 0:
        return False

    # Process up to GAZETTEER_BATCH_SIZE articles per run
    # (or all pending if less than batch size)
    limit = min(count, GAZETTEER_BATCH_SIZE)
    
    command = [
        "extract-entities",
        "--limit",
        str(limit),
    ]

    return run_cli_command(
        command, f"Entity extraction ({count} pending, limit {limit})"
    )


def process_cycle() -> None:
    """Run one processing cycle: check for work and execute tasks."""
    logger.info("🔍 Checking for pending work...")

    try:
        counts = WorkQueue.get_counts()
        logger.info("Work queue status: %s", counts)

        # Priority order: verification → extraction → cleaning → analysis → entities
        # This ensures we process the pipeline in the correct sequence

        if counts["verification_pending"] > 0:
            process_verification(counts["verification_pending"])

        if counts["extraction_pending"] > 0:
            process_extraction(counts["extraction_pending"])

        if counts["cleaning_pending"] > 0:
            process_cleaning(counts["cleaning_pending"])

        if counts["analysis_pending"] > 0:
            process_analysis(counts["analysis_pending"])

        if counts["entity_extraction_pending"] > 0:
            process_entity_extraction(counts["entity_extraction_pending"])

        # If nothing to do, log idle status
        if all(count == 0 for count in counts.values()):
            logger.info("💤 No pending work, sleeping for %d seconds", POLL_INTERVAL)

    except Exception as exc:
        logger.exception("💥 Error during processing cycle: %s", exc)


def main() -> None:
    """Main loop: continuously monitor and process work."""
    logger.info("🚀 Starting continuous processor")
    logger.info("Configuration:")
    logger.info("  - Poll interval: %d seconds", POLL_INTERVAL)
    logger.info("  - Verification batch size: %d", VERIFICATION_BATCH_SIZE)
    logger.info("  - Extraction batch size: %d", EXTRACTION_BATCH_SIZE)
    logger.info("  - Analysis batch size: %d", ANALYSIS_BATCH_SIZE)
    logger.info("  - Gazetteer batch size: %d", GAZETTEER_BATCH_SIZE)

    cycle_count = 0

    while True:
        cycle_count += 1
        logger.info("=" * 60)
        logger.info("Processing cycle #%d", cycle_count)

        try:
            process_cycle()
        except KeyboardInterrupt:
            logger.info("⏹️  Received interrupt signal, shutting down")
            break
        except Exception as exc:
            logger.exception("💥 Unexpected error in main loop: %s", exc)

        # Sleep until next cycle
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
