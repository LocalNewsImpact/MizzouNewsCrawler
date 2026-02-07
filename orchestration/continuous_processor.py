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

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from src.models import Article, CandidateLink
from src.models.database import DatabaseManager
from src.services.wire_detection import (
    DEFAULT_RATE_PER_MINUTE,
    MediaCloudArticle,
    MediaCloudDetector,
    resolve_api_token,
)
from src.utils.content_cleaning_telemetry import ContentCleaningTelemetry

# In containerized environments (GKE/Cloud Run), platform adds timestamps.
# Use simple format to avoid duplication in logs.
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize telemetry for wire detection logging
telemetry = ContentCleaningTelemetry(enable_telemetry=True)

# Configuration from environment
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))  # seconds
IDLE_POLL_INTERVAL = int(
    os.getenv(
        "IDLE_POLL_INTERVAL",
        os.getenv("IDLE_SLEEP_SECONDS", "300"),
    )
)  # seconds, used when no work is pending
VERIFICATION_BATCH_SIZE = int(os.getenv("VERIFICATION_BATCH_SIZE", "10"))
EXTRACTION_BATCH_SIZE = int(os.getenv("EXTRACTION_BATCH_SIZE", "20"))
ANALYSIS_BATCH_SIZE = int(os.getenv("ANALYSIS_BATCH_SIZE", "16"))
GAZETTEER_BATCH_SIZE = int(os.getenv("GAZETTEER_BATCH_SIZE", "500"))

# Feature flags for pipeline steps (can be disabled for dataset-specific jobs)
ENABLE_DISCOVERY = os.getenv("ENABLE_DISCOVERY", "false").lower() == "true"
ENABLE_VERIFICATION = os.getenv("ENABLE_VERIFICATION", "false").lower() == "true"
ENABLE_EXTRACTION = os.getenv("ENABLE_EXTRACTION", "false").lower() == "true"
ENABLE_CLEANING = os.getenv("ENABLE_CLEANING", "true").lower() == "true"
ENABLE_ML_ANALYSIS = os.getenv("ENABLE_ML_ANALYSIS", "true").lower() == "true"
ENABLE_ENTITY_EXTRACTION = (
    os.getenv("ENABLE_ENTITY_EXTRACTION", "true").lower() == "true"
)
WIRE_DETECTION_BATCH_SIZE = int(os.getenv("WIRE_DETECTION_BATCH_SIZE", "1"))
MEDIACLOUD_RATE_PER_MINUTE = float(
    os.getenv("MEDIACLOUD_RATE_PER_MINUTE", str(DEFAULT_RATE_PER_MINUTE))
)
_WIRE_ENV_ENABLED = os.getenv("ENABLE_WIRE_DETECTION", "true").lower() == "true"
_MEDIACLOUD_TOKEN = resolve_api_token(logger=logger)
ENABLE_WIRE_DETECTION = bool(_WIRE_ENV_ENABLED and _MEDIACLOUD_TOKEN)
WIRE_DETECTION_ALLOWED_STATUSES = ("cleaned", "local", "labeled", "classified")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_MODULE = "src.cli.cli_modular"

if _WIRE_ENV_ENABLED and not ENABLE_WIRE_DETECTION:
    logger.warning(
        "MediaCloud wire detection disabled: ENABLE_WIRE_DETECTION=true but MEDIACLOUD_API_TOKEN not set"
    )


class WorkQueue:
    """Check database for pending work."""

    @staticmethod
    def get_counts() -> dict[str, int]:
        """Return counts of work items in each stage.

        Only queries for enabled pipeline steps to reduce unnecessary database load.
        """
        counts = {
            "verification_pending": 0,
            "extraction_pending": 0,
            "cleaning_pending": 0,
            "analysis_pending": 0,
            "entity_extraction_pending": 0,
            "wire_detection_pending": 0,
        }

        with DatabaseManager() as db:
            # Count candidate_links needing verification (only if enabled)
            if ENABLE_VERIFICATION:
                result = db.session.execute(
                    text(
                        "SELECT COUNT(*) FROM candidate_links "
                        "WHERE status = 'discovered'"
                    )
                )
                counts["verification_pending"] = result.scalar() or 0

            # Count candidate_links ready for extraction (only if enabled)
            # Only count those that haven't been extracted yet
            if ENABLE_EXTRACTION:
                result = db.session.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM candidate_links
                        WHERE status = 'article'
                        AND id NOT IN (
                            SELECT candidate_link_id FROM articles
                            WHERE candidate_link_id IS NOT NULL
                        )
                        """
                    )
                )
                counts["extraction_pending"] = result.scalar() or 0

            # Count articles needing cleaning (status = extracted)
            if ENABLE_CLEANING:
                result = db.session.execute(
                    text(
                        "SELECT COUNT(*) FROM articles "
                        "WHERE status = 'extracted' AND content IS NOT NULL"
                    )
                )
                counts["cleaning_pending"] = result.scalar() or 0

            # Count articles without ML analysis (cleaned articles are ready for ML)
            if ENABLE_ML_ANALYSIS:
                result = db.session.execute(
                    text(
                        "SELECT COUNT(*) FROM articles "
                        "WHERE status IN ('cleaned', 'local') "
                        "AND wire_check_status != 'wire' "
                        "AND primary_label IS NULL"
                    )
                )
                counts["analysis_pending"] = result.scalar() or 0

            # Count articles without entity extraction
            # (labeled articles are ready for entity extraction)
            if ENABLE_ENTITY_EXTRACTION:
                result = db.session.execute(
                    text(
                        "SELECT COUNT(*) FROM articles a "
                        "WHERE a.status = 'labeled' "
                        "AND NOT EXISTS ("
                        "  SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id"
                        ") AND a.content IS NOT NULL"
                    )
                )
                counts["entity_extraction_pending"] = result.scalar() or 0

            if ENABLE_WIRE_DETECTION:
                result = db.session.execute(
                    text(
                        "SELECT COUNT(*) FROM articles "
                        "WHERE wire_check_status = 'pending' "
                        "AND status IN ('cleaned', 'local', 'labeled', 'classified')"
                    )
                )
                counts["wire_detection_pending"] = result.scalar() or 0

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
                    # Print directly to avoid double timestamps in Cloud Logging
                    print(line.rstrip(), flush=True)

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
        "--statuses",
        "cleaned",
        "local",
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


# Global cached entity extractor (loaded once at startup, never reloaded)
_ENTITY_EXTRACTOR = None
_MEDIACLOUD_DETECTOR = None


def get_cached_entity_extractor():
    """Get or create cached entity extractor with spaCy model loaded once.

    This avoids reloading the spaCy model on every batch, which was causing
    288 model reloads per day (wasting 10 min/day + 2GB memory spikes).
    """
    global _ENTITY_EXTRACTOR
    if _ENTITY_EXTRACTOR is None:
        from src.pipeline.entity_extraction import ArticleEntityExtractor
        logger.info("🧠 Loading spaCy model (one-time initialization)...")
        _ENTITY_EXTRACTOR = ArticleEntityExtractor()
        logger.info("✅ spaCy model loaded and cached in memory")
    return _ENTITY_EXTRACTOR


def get_mediacloud_detector() -> MediaCloudDetector | None:
    global _MEDIACLOUD_DETECTOR
    if not ENABLE_WIRE_DETECTION:
        return None
    if _MEDIACLOUD_DETECTOR is None:
        try:
            _MEDIACLOUD_DETECTOR = MediaCloudDetector.from_token(
                _MEDIACLOUD_TOKEN,
                rate_per_minute=MEDIACLOUD_RATE_PER_MINUTE,
                logger=logger,
            )
        except Exception:
            logger.exception("Failed to initialise MediaCloud detector; disabling wire detection")
            return None
    return _MEDIACLOUD_DETECTOR


@dataclass
class PendingWireArticle:
    id: str
    url: str
    title: str
    source: str
    extracted_at: datetime | None
    status: str


def _claim_wire_articles(limit: int) -> list[PendingWireArticle]:
    claimed: list[PendingWireArticle] = []
    attempts = 0

    while len(claimed) < limit and attempts < limit * 3:
        attempts += 1
        with DatabaseManager() as db:
            session = db.session

            article = (
                session.query(Article)
                .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
                .filter(
                    Article.wire_check_status == "pending",
                    Article.status.in_(WIRE_DETECTION_ALLOWED_STATUSES),
                )
                .order_by(Article.extracted_at)
                .with_for_update(of=Article, nowait=False)
                .first()
            )

            if article is None:
                break

            source = article.candidate_link.source if article.candidate_link else ""

            updated = (
                session.query(Article)
                .filter(Article.id == article.id, Article.wire_check_status == "pending")
                .update(
                    {
                        Article.wire_check_status: "processing",
                        Article.wire_check_attempted_at: datetime.utcnow(),
                        Article.wire_check_error: None,
                    },
                    synchronize_session=False,
                )
            )

            if updated != 1:
                session.rollback()
                continue

            session.commit()

            claimed.append(
                PendingWireArticle(
                    id=article.id,
                    url=article.url or "",
                    title=article.title or "",
                    source=source or "",
                    extracted_at=article.extracted_at,
                    status=article.status or "",
                )
            )

    return claimed


def _apply_detection_result(
    pending: PendingWireArticle,
    result,
) -> bool:
    with DatabaseManager() as db:
        session = db.session
        article = session.query(Article).filter(Article.id == pending.id).one_or_none()
        if article is None:
            return False

        attempted_at = result.queried_at
        if attempted_at and getattr(attempted_at, "tzinfo", None):
            attempted_at = attempted_at.astimezone(timezone.utc).replace(tzinfo=None)
        article.wire_check_attempted_at = attempted_at

        metadata = result.to_metadata()
        article.wire_check_metadata = metadata

        if result.status != "ok":
            article.wire_check_status = "error"
            article.wire_check_error = result.status
            session.commit()
            logger.warning(
                "MediaCloud lookup failed for article %s with status %s",
                pending.id,
                result.status,
            )
            return False

        article.wire_check_status = "complete"
        article.wire_check_error = None

        matched = result.has_matches

        if matched:
            existing_payload = article.wire
            if isinstance(existing_payload, str):
                try:
                    existing_payload = json.loads(existing_payload)
                except json.JSONDecodeError:
                    existing_payload = {}
            if not isinstance(existing_payload, dict):
                existing_payload = {}

            wire_payload = result.to_wire_payload()
            wire_payload.setdefault("detected_at", datetime.utcnow().isoformat() + "Z")
            existing_payload.update(wire_payload)
            article.wire = existing_payload

            # Log telemetry for wire detection
            telemetry.log_wire_detection(
                provider="mediacloud",
                detection_method="headline_duplicate",
                detection_stage="mediacloud_lookup",
                confidence=1.0,  # MediaCloud matches are considered high confidence
                article_ids=[pending.id],
                domain=pending.source,
                pattern_text=result.query,
                extra_metadata={
                    "story_count": result.story_count,
                    "matched_story_count": result.matched_story_count,
                    "matched_hosts": result.matched_hosts,
                    "matched_story_ids": result.matched_story_ids,
                },
            )

            if article.status != "wire":
                article.status = "wire"

            if article.candidate_link:
                article.candidate_link.status = "wire"

        session.commit()

        return matched


def process_wire_detection(count: int) -> bool:
    if not ENABLE_WIRE_DETECTION or count == 0:
        return False

    detector = get_mediacloud_detector()
    if detector is None:
        return False

    # Start telemetry session for wire detection
    _ = telemetry.start_cleaning_session(
        domain="mediacloud_wire_detection",
        article_count=count,
    )

    limit = min(count, max(1, WIRE_DETECTION_BATCH_SIZE))
    pending_articles = _claim_wire_articles(limit)
    if not pending_articles:
        telemetry.finalize_cleaning_session()
        return False

    processed_any = False

    for pending in pending_articles:
        extracted_at = pending.extracted_at
        if extracted_at:
            if extracted_at.tzinfo is None:
                extracted_at = extracted_at.replace(tzinfo=timezone.utc)
            else:
                extracted_at = extracted_at.astimezone(timezone.utc)
        media_article = MediaCloudArticle(
            article_id=pending.id,
            source=pending.source,
            url=pending.url,
            title=pending.title,
            extracted_at=extracted_at,
        )
        result = detector.detect(media_article)
        matched = _apply_detection_result(pending, result)
        processed_any = True

        if result.status == "ok" and matched:
            logger.info(
                "MediaCloud marked article %s as wire (hosts=%s)",
                pending.id,
                ", ".join(result.matched_hosts),
            )
        elif result.status == "ok":
            logger.debug("MediaCloud found no wire matches for article %s", pending.id)

    # Finalize telemetry session
    telemetry.finalize_cleaning_session(
        rough_candidates_found=0,
        segments_detected=0,
        total_removable_chars=0,
        removal_percentage=0.0,
    )

    return processed_any


def process_entity_extraction(count: int) -> bool:
    """Run entity extraction on articles that have content but no entities.

    This command extracts location entities from article text and stores
    them in the article_entities table. The gazetteer data (OSM locations
    for each source) should already be populated via the populate-gazetteer
    command during initial setup.

    Uses a cached extractor to avoid reloading the spaCy model on every batch.
    """
    if count == 0:
        return False

    # Process up to GAZETTEER_BATCH_SIZE articles per run
    # (or all pending if less than batch size)
    limit = min(count, GAZETTEER_BATCH_SIZE)

    try:
        from argparse import Namespace
        from src.cli.commands.entity_extraction import handle_entity_extraction_command

        logger.info("▶️  Entity extraction (%d pending, limit %d)", count, limit)

        # Get cached extractor (model already loaded!)
        extractor = get_cached_entity_extractor()

        # Call directly instead of subprocess to keep model in memory
        args = Namespace(limit=limit, source=None)
        start = time.time()
        result = handle_entity_extraction_command(args, extractor=extractor)
        elapsed = time.time() - start

        if result == 0:
            logger.info("✅ Entity extraction completed successfully (%.1fs)", elapsed)
            return True
        else:
            logger.error(
                "❌ Entity extraction failed with exit code %d (%.1fs)",
                result,
                elapsed,
            )
            return False

    except Exception as e:
        logger.exception("💥 Entity extraction raised exception: %s", e)
        return False


def process_cycle() -> bool:
    """Run one processing cycle: check for work and execute tasks.

    Returns True when any eligible work exists for enabled steps, allowing the
    caller to decide how long to pause before the next cycle.
    """
    logger.info("🔍 Checking for pending work...")

    try:
        counts = WorkQueue.get_counts()
        logger.info("Work queue status: %s", counts)

        pending_flags = [
            ENABLE_VERIFICATION and counts["verification_pending"] > 0,
            ENABLE_EXTRACTION and counts["extraction_pending"] > 0,
            ENABLE_CLEANING and counts["cleaning_pending"] > 0,
            ENABLE_WIRE_DETECTION and counts["wire_detection_pending"] > 0,
            ENABLE_ML_ANALYSIS and counts["analysis_pending"] > 0,
            ENABLE_ENTITY_EXTRACTION and counts["entity_extraction_pending"] > 0,
        ]

        has_pending_work = any(pending_flags)

        # Priority order: verification → extraction → cleaning → wire detection → analysis → entities
        # This ensures we process the pipeline in the correct sequence
        # Only run enabled steps (controlled by environment variables)

        if ENABLE_VERIFICATION and counts["verification_pending"] > 0:
            process_verification(counts["verification_pending"])

        if ENABLE_EXTRACTION and counts["extraction_pending"] > 0:
            process_extraction(counts["extraction_pending"])

        if ENABLE_CLEANING and counts["cleaning_pending"] > 0:
            process_cleaning(counts["cleaning_pending"])

        if ENABLE_WIRE_DETECTION and counts["wire_detection_pending"] > 0:
            process_wire_detection(counts["wire_detection_pending"])

        if ENABLE_ML_ANALYSIS and counts["analysis_pending"] > 0:
            process_analysis(counts["analysis_pending"])

        if ENABLE_ENTITY_EXTRACTION and counts["entity_extraction_pending"] > 0:
            process_entity_extraction(counts["entity_extraction_pending"])

        if not has_pending_work:
            logger.info("💤 No pending work detected this cycle")

        return has_pending_work
    except Exception as exc:
        logger.exception("💥 Error during processing cycle: %s", exc)
        return True


def main() -> None:
    """Main loop: continuously monitor and process work."""
    logger.info("🚀 Starting continuous processor")
    logger.info("Configuration:")
    logger.info("  - Poll interval: %d seconds", POLL_INTERVAL)
    logger.info("  - Idle poll interval: %d seconds", IDLE_POLL_INTERVAL)
    logger.info("  - Verification batch size: %d", VERIFICATION_BATCH_SIZE)
    logger.info("  - Extraction batch size: %d", EXTRACTION_BATCH_SIZE)
    logger.info("  - Analysis batch size: %d", ANALYSIS_BATCH_SIZE)
    logger.info("  - Gazetteer batch size: %d", GAZETTEER_BATCH_SIZE)
    logger.info("")
    logger.info("Enabled pipeline steps:")
    logger.info("  - Discovery: %s", "✅" if ENABLE_DISCOVERY else "❌")
    logger.info("  - Verification: %s", "✅" if ENABLE_VERIFICATION else "❌")
    logger.info("  - Extraction: %s", "✅" if ENABLE_EXTRACTION else "❌")
    logger.info("  - Cleaning: %s", "✅" if ENABLE_CLEANING else "❌")
    logger.info("  - Wire Detection: %s", "✅" if ENABLE_WIRE_DETECTION else "❌")
    logger.info("  - ML Analysis: %s", "✅" if ENABLE_ML_ANALYSIS else "❌")
    logger.info("  - Entity Extraction: %s", "✅" if ENABLE_ENTITY_EXTRACTION else "❌")

    # Warn if no steps are enabled
    if not any([
        ENABLE_DISCOVERY,
        ENABLE_VERIFICATION,
        ENABLE_EXTRACTION,
        ENABLE_CLEANING,
        ENABLE_WIRE_DETECTION,
        ENABLE_ML_ANALYSIS,
        ENABLE_ENTITY_EXTRACTION,
    ]):
        logger.warning("⚠️  No pipeline steps are enabled! Processor will be idle.")

    cycle_count = 0

    while True:
        cycle_count += 1
        logger.info("=" * 60)
        logger.info("Processing cycle #%d", cycle_count)

        try:
            pending_work = process_cycle()
        except KeyboardInterrupt:
            logger.info("⏹️  Received interrupt signal, shutting down")
            break
        except Exception as exc:
            logger.exception("💥 Unexpected error in main loop: %s", exc)
            pending_work = True

        # Sleep until next cycle
        sleep_seconds = POLL_INTERVAL if pending_work else IDLE_POLL_INTERVAL
        reason = "pending work" if pending_work else "idle"
        logger.info("⏸️  Sleeping for %d seconds (%s)", sleep_seconds, reason)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
