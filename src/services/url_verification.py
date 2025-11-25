#!/usr/bin/env python3
"""
URL Verification Service using StorySniffer.

This service processes URLs with 'discovered' status and verifies them
using StorySniffer to determine if they are articles or not.
"""

import argparse
import inspect
import logging
import os
import re
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import urllib3
from requests import Session
from requests.exceptions import RequestException, Timeout

# Suppress InsecureRequestWarning for proxies without SSL certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import after path modification
try:
    import storysniffer
except ImportError:
    print("Error: storysniffer not installed. Run: pip install storysniffer")
    sys.exit(1)

from src.crawler.origin_proxy import enable_origin_proxy  # noqa: E402
from src.crawler.proxy_config import get_proxy_manager  # noqa: E402
from src.models.database import DatabaseManager, safe_execute  # noqa: E402
from src.utils.telemetry import (  # noqa: E402
    OperationTracker,
    create_telemetry_system,
)

_DEFAULT_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_FALLBACK_GET_STATUSES = {403, 405}
_RETRYABLE_STATUS_CODES = {429}
_GET_FALLBACK_ATTEMPTS = 3
_GET_FALLBACK_BACKOFF = 0.5  # seconds (exponential backoff)

# Small pool of alternative User-Agent strings to use when sites block a single UA
_ALT_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/117.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/115.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_0) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/15.1 Safari/605.1.15"
    ),
]


class URLVerificationService:
    """Service to verify URLs with StorySniffer and update their status."""

    def __init__(
        self,
        batch_size: int = 100,
        sleep_interval: int = 30,
        run_http_precheck: bool | None = None,
        *,
        http_session: Session | None = None,
        http_timeout: float = 5.0,
        http_retry_attempts: int = 3,
        http_backoff_seconds: float = 0.5,
        http_headers: Mapping[str, str] | None = None,
        telemetry_tracker: OperationTracker | None = None,
    ):
        """Initialize the verification service.

        Args:
            batch_size: Number of URLs to process in each batch
            sleep_interval: Seconds to wait between batches when no work
            telemetry_tracker: Optional telemetry tracker for recording metrics
        """
        self.batch_size = batch_size
        self.sleep_interval = sleep_interval

        # Initialize telemetry
        if telemetry_tracker is None:
            telemetry_tracker = create_telemetry_system()
        self.telemetry = telemetry_tracker
        # Determine whether to run lightweight HTTP checks before StorySniffer.
        # Default is False to preserve existing test behavior. If the caller
        # passes None, consult the environment variable RUN_HTTP_PRECHECK.
        if run_http_precheck is None:
            env_val = os.getenv("RUN_HTTP_PRECHECK", "").lower()
            self.run_http_precheck = env_val in ("1", "true", "yes")
        else:
            self.run_http_precheck = bool(run_http_precheck)
        # (debug logging removed)
        self.db = DatabaseManager()
        self.sniffer = storysniffer.StorySniffer()
        self.logger = logging.getLogger(__name__)
        self.http_session = http_session or requests.Session()
        self.http_timeout = http_timeout
        self.http_retry_attempts = max(1, http_retry_attempts)
        self.http_backoff_seconds = max(0.0, http_backoff_seconds)
        self.http_headers = dict(_DEFAULT_HTTP_HEADERS)
        if http_headers:
            self.http_headers.update(http_headers)
        self.proxy_manager = get_proxy_manager()
        self._configure_proxy()
        self._prepare_http_session()
        self.running = False

    def _configure_proxy(self) -> None:
        """Configure HTTP session proxy routing according to provider settings."""

        active_provider = self.proxy_manager.active_provider
        self.logger.info(
            "🔀 Verification proxy provider: %s",
            active_provider.value,
        )

        use_origin_proxy = os.getenv("USE_ORIGIN_PROXY", "").lower() in (
            "1",
            "true",
            "yes",
        )

        if active_provider.value == "origin" or use_origin_proxy:
            try:
                enable_origin_proxy(self.http_session)
                proxy_base = (
                    self.proxy_manager.get_origin_proxy_url()
                    or os.getenv("ORIGIN_PROXY_URL")
                    or os.getenv("PROXY_URL")
                    or "default"
                )
                self.logger.info(
                    "🔐 Verification using origin proxy adapter (%s)",
                    proxy_base,
                )
            except Exception as exc:
                self.logger.warning(
                    "Failed to install origin proxy adapter for verification: %s",
                    exc,
                )
            return

        proxies = self.proxy_manager.get_requests_proxies()
        if proxies:
            self.http_session.proxies.update(proxies)
            self.logger.info(
                "🔐 Verification using %s provider (%s)",
                active_provider.value,
                ", ".join(sorted(proxies.keys())),
            )
        else:
            self.logger.info(
                "🔐 Proxy provider %s did not supply proxies; using direct connections",
                active_provider.value,
            )

    def get_unverified_urls(self, limit: int | None = None) -> list[dict]:
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
            result = safe_execute(conn, query)
            return [dict(row._mapping) for row in result.fetchall()]

    def _prepare_http_session(self) -> None:
        """Ensure the HTTP session advertises browser-like headers."""

        session_headers = getattr(self.http_session, "headers", None)
        if session_headers is None:
            self.http_session.headers = dict(self.http_headers)
            return

        if not hasattr(session_headers, "setdefault"):
            # Unexpected type; fall back to a fresh mapping.
            self.http_session.headers = dict(self.http_headers)
            return

        for key, value in self.http_headers.items():
            if key not in session_headers:
                session_headers[key] = value

    def _check_http_health(self, url: str) -> tuple[bool, int | None, str | None, int]:
        """Perform a lightweight HTTP check with retries.

        Returns a tuple of (is_successful, status_code, error_message,
        attempts).
        """

        attempts = 0
        last_error: str | None = None
        status_code: int | None = None

        while attempts < self.http_retry_attempts:
            attempts += 1

            try:
                response = self.http_session.head(
                    url,
                    allow_redirects=True,
                    timeout=self.http_timeout,
                )
                status_code = getattr(response, "status_code", None)

                if status_code is None:
                    last_error = "missing status code"
                elif 500 <= status_code < 600:
                    last_error = f"HTTP {status_code}"
                elif status_code in _RETRYABLE_STATUS_CODES:
                    last_error = f"HTTP {status_code} (rate limited)"
                elif status_code >= 400:
                    if self._should_attempt_get_fallback(status_code):
                        fallback_ok, fallback_status, fallback_error = (
                            self._attempt_get_fallback(url)
                        )
                        status_code = fallback_status or status_code
                        if fallback_ok:
                            return True, status_code, None, attempts

                        last_error = fallback_error or f"HTTP {status_code}"
                    else:
                        return (
                            False,
                            status_code,
                            f"HTTP {status_code}",
                            attempts,
                        )
                else:
                    return True, status_code, None, attempts

            except Timeout:
                last_error = f"timeout after {self.http_timeout}s"
            except RequestException as exc:
                status_code = getattr(
                    getattr(exc, "response", None),
                    "status_code",
                    None,
                )
                last_error = str(exc)

            if attempts < self.http_retry_attempts:
                time.sleep(self.http_backoff_seconds)
                continue

            break

        if last_error is None:
            last_error = "HTTP check failed"

        return False, status_code, last_error, attempts

    @staticmethod
    def _should_attempt_get_fallback(status_code: int | None) -> bool:
        return bool(status_code) and status_code in _FALLBACK_GET_STATUSES

    def _attempt_get_fallback(self, url: str) -> tuple[bool, int | None, str | None]:
        """Attempt a GET request when HEAD is blocked by the origin."""
        # Try a few GET attempts with slight backoff and rotating User-Agent values.
        response = None
        last_error: str | None = None
        status_code: int | None = None

        # Save original headers so we can restore them after attempts
        original_headers = dict(getattr(self.http_session, "headers", {}) or {})

        for attempt in range(1, _GET_FALLBACK_ATTEMPTS + 1):
            try:
                # Rotate User-Agent on retry attempts to evade simple UA blocks
                if attempt > 1:
                    ua = _ALT_USER_AGENTS[(attempt - 2) % len(_ALT_USER_AGENTS)]
                    self.http_session.headers["User-Agent"] = ua

                response = self.http_session.get(  # type: ignore[attr-defined]
                    url,
                    allow_redirects=True,
                    timeout=self.http_timeout,
                    stream=True,
                )
                status_code = getattr(response, "status_code", None)
                if status_code is None:
                    last_error = "missing status code from GET"
                elif status_code < 400:
                    # restore headers
                    self.http_session.headers = original_headers
                    return True, status_code, None
                else:
                    last_error = f"HTTP {status_code}"

            except Timeout:
                last_error = f"timeout after {self.http_timeout}s during GET fallback"
            except RequestException as exc:
                status_code = getattr(
                    getattr(exc, "response", None),
                    "status_code",
                    None,
                )
                last_error = str(exc)
            finally:
                if response is not None:
                    close_fn = getattr(response, "close", None)
                    if callable(close_fn):
                        close_fn()

            # If not the last attempt, sleep with exponential backoff
            if attempt < _GET_FALLBACK_ATTEMPTS:
                time.sleep(_GET_FALLBACK_BACKOFF * (2 ** (attempt - 1)))

        # restore headers
        self.http_session.headers = original_headers
        if last_error is None:
            last_error = "GET fallback failed"
        return False, status_code, last_error

    def verify_url(self, url: str) -> dict:
        """Verify a single URL with pattern matching and StorySniffer.

        Uses a three-stage verification process:
        1. Check for wire service URLs (skip extraction entirely)
        2. Fast URL pattern matching to filter obvious non-articles
        3. StorySniffer ML model for remaining URLs

        Returns:
            Dict with verification results and timing info
        """
        start_time = time.time()
        result = {
            "url": url,
            "storysniffer_result": None,
            "verification_time_ms": 0.0,
            "error": None,
            "http_status": None,
            "http_attempts": 0,
            "pattern_filtered": False,
            "wire_filtered": False,
        }

        # Stage 0: Check for wire service URLs (highest priority)
        from src.utils.content_type_detector import ContentTypeDetector

        detector = ContentTypeDetector()
        # Quick URL-only wire detection (no content needed)
        wire_patterns = detector._get_wire_service_patterns(pattern_type="url")
        
        for pattern, service_name, case_sensitive in wire_patterns:
            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(pattern, url, flags):
                # This is a wire service URL - mark immediately
                result["storysniffer_result"] = False
                result["wire_filtered"] = True
                result["wire_service"] = service_name
                result["verification_time_ms"] = (time.time() - start_time) * 1000
                self.logger.debug(
                    f"Filtered wire service URL: {url} ({service_name}) "
                    f"({result['verification_time_ms']:.1f}ms)"
                )
                return result

        # Stage 1: Fast URL pattern check
        from src.utils.url_classifier import is_likely_article_url

        if not is_likely_article_url(url):
            # URL matches non-article pattern (gallery, category, etc.)
            result["storysniffer_result"] = False
            result["pattern_filtered"] = True
            result["verification_time_ms"] = (time.time() - start_time) * 1000
            self.logger.debug(
                f"Filtered non-article by URL pattern: {url} "
                f"({result['verification_time_ms']:.1f}ms)"
            )
            return result

        # Branching behavior: by default we run StorySniffer first and
        # short-circuit (this matches test expectations). When
        # `self.run_http_precheck` is True (production opt-in), perform a
        # lightweight HTTP health check first and only call StorySniffer
        # if the HTTP check passes.
        if self.run_http_precheck:
            # Perform HTTP pre-checks before invoking the heavier ML model.
            try:
                ok, status_code, error_msg, attempts = self._check_http_health(url)
                result["http_status"] = status_code
                result["http_attempts"] = attempts

                if not ok:
                    result["error"] = error_msg
                    result["verification_time_ms"] = (time.time() - start_time) * 1000
                    self.logger.warning(f"HTTP check failed for {url}: {error_msg}")
                    return result
            except Exception as e:
                result["error"] = str(e)
                result["verification_time_ms"] = (time.time() - start_time) * 1000
                self.logger.warning(f"HTTP health check exception for {url}: {e}")
                return result

            # If HTTP pre-checks passed, run the sniffer.
            try:
                is_article = self.sniffer.guess(url)
                result["storysniffer_result"] = (
                    bool(is_article) if is_article is not None else None
                )
                result["verification_time_ms"] = (time.time() - start_time) * 1000

                self.logger.debug(
                    f"Verified {url}: "
                    f"{'article' if is_article else 'not_article'} "
                    f"({result['verification_time_ms']:.1f}ms)"
                )
            except Exception as e:
                result["error"] = str(e)
                result["verification_time_ms"] = (time.time() - start_time) * 1000
                self.logger.warning(f"Verification failed for {url}: {e}")
            return result

        else:
            # Default path: run StorySniffer first and skip HTTP checks
            # entirely so behavior remains stable for tests and for
            # existing pipelines that expect sniffer-first semantics.
            try:
                is_article = self.sniffer.guess(url)
                result["storysniffer_result"] = (
                    bool(is_article) if is_article is not None else None
                )
                result["verification_time_ms"] = (time.time() - start_time) * 1000

                self.logger.debug(
                    f"Verified {url}: "
                    f"{'article' if is_article else 'not_article'} "
                    f"({result['verification_time_ms']:.1f}ms)"
                )

                return result
            except Exception as e:
                result["error"] = str(e)
                result["storysniffer_result"] = None
                result["verification_time_ms"] = (time.time() - start_time) * 1000
                self.logger.warning(f"Verification failed for {url}: {e}")
                return result

    def update_candidate_status(
        self, candidate_id: str, new_status: str, error_message: str | None = None
    ):
        """Update candidate_links status based on verification."""
        update_data = {
            "candidate_id": candidate_id,
            "status": new_status,
            "processed_at": datetime.now(),
        }

        if error_message:
            update_data["error_message"] = error_message

        update_query = """
            UPDATE candidate_links
            SET status = :status, processed_at = :processed_at
        """

        if error_message:
            update_query += ", error_message = :error_message"

        update_query += " WHERE id = :candidate_id"

        with self.db.engine.connect() as conn:
            safe_execute(conn, update_query, update_data)
            # some connection implementations expose commit() on the
            # connection object; preserve existing behavior.
            try:
                conn.commit()
            except Exception:
                # If the proxied/underlying connection doesn't support
                # commit(), it's fine because the higher-level session
                # or engine-managed transaction will handle commits.
                pass

        self.logger.debug(f"Updated candidate {candidate_id} to: {new_status}")

    def process_batch(self, candidates: list[dict]) -> dict:
        """Process a batch of candidates and return metrics."""
        batch_metrics: dict = {
            "total_processed": 0,
            "verified_articles": 0,
            "verified_non_articles": 0,
            "verification_errors": 0,
            "total_time_ms": 0.0,
            "batch_time_seconds": 0.0,
            "avg_verification_time_ms": 0.0,
        }

        batch_start_time = time.time()

        for candidate in candidates:
            # Verify URL
            verification_result = self.verify_url(candidate["url"])
            batch_metrics["total_processed"] += 1

            # Determine new status and update metrics
            if verification_result.get("error"):
                batch_metrics["verification_errors"] += 1
                # If we ran HTTP pre-checks (production opt-in), treat
                # exhausted HTTP failures as a terminal verification
                # failure so orchestration can move candidates to the
                # failed bucket. When running the default sniffer-first
                # test-friendly path, preserve the non-terminal
                # 'verification_uncertain' status so unit tests and
                # manual review flows can retry or inspect candidates.
                if self.run_http_precheck:
                    new_status = "verification_failed"
                else:
                    new_status = "verification_uncertain"
                error_message = verification_result["error"]
            elif verification_result.get("wire_filtered"):
                # Wire service URL detected - mark as wire
                batch_metrics["verified_non_articles"] += 1
                new_status = "wire"
                error_message = None
            elif verification_result.get("storysniffer_result"):
                batch_metrics["verified_articles"] += 1
                new_status = "article"
                error_message = None
            else:
                batch_metrics["verified_non_articles"] += 1
                new_status = "not_article"
                error_message = None

            batch_metrics["total_time_ms"] += verification_result.get(
                "verification_time_ms", 0
            )

            # Update candidate status
            self.update_candidate_status(candidate["id"], new_status, error_message)

        # Calculate batch timing
        batch_metrics["batch_time_seconds"] = time.time() - batch_start_time
        batch_metrics["avg_verification_time_ms"] = (
            batch_metrics["total_time_ms"] / batch_metrics["total_processed"]
            if batch_metrics["total_processed"] > 0
            else 0.0
        )

        return batch_metrics

    def save_telemetry_summary(
        self, batch_metrics: dict, candidates: list[dict], job_name: str
    ):
        """Save telemetry summary to database."""
        sources = list(set(c.get("source_name", "Unknown") for c in candidates))

        self.telemetry.record_verification_batch(
            job_name=job_name,
            batch_size=len(candidates),
            verified_articles=batch_metrics.get("verified_articles", 0),
            verified_non_articles=batch_metrics.get("verified_non_articles", 0),
            verification_errors=batch_metrics.get("verification_errors", 0),
            total_processed=batch_metrics.get("total_processed", 0),
            batch_time_seconds=batch_metrics.get("batch_time_seconds", 0.0),
            avg_verification_time_ms=batch_metrics.get("avg_verification_time_ms", 0.0),
            total_time_ms=batch_metrics.get("total_time_ms", 0.0),
            sources_processed=sources,
        )

        self.logger.info(
            "Verification telemetry recorded to database: "
            f"{batch_metrics.get('total_processed', 0)} URLs processed"
        )

    def run_verification_loop(
        self,
        *,
        max_batches: int | None = None,
        exit_on_idle: bool = False,
        idle_grace_seconds: int | float | None = None,
    ) -> None:
        """Run the main verification loop.

        Args:
            max_batches: Optional hard cap on the number of batches to process.
            exit_on_idle: When True, stop the loop once no work is available
                instead of sleeping and polling again.
            idle_grace_seconds: Optional grace period to continue polling when
                no work is available before exiting due to idleness.
        """
        self.running = True
        batch_count = 0
        job_name = f"verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        idle_start_monotonic: float | None = None
        idle_wait_logged = False

        self.logger.info(
            f"Starting verification loop: {job_name} "
            f"(batch_size={self.batch_size}, "
            f"sleep_interval={self.sleep_interval}s)"
        )

        try:
            while self.running:
                # Respect explicit batch caps before polling for new work.
                if max_batches and batch_count >= max_batches:
                    self.logger.info(
                        "Reached configured max_batches=%s; exiting.",
                        max_batches,
                    )
                    break

                # Get unverified URLs
                candidates = self.get_unverified_urls(self.batch_size)

                if not candidates:
                    if idle_start_monotonic is None:
                        idle_start_monotonic = time.monotonic()
                        idle_wait_logged = False

                    if max_batches and batch_count >= max_batches:
                        self.logger.info(
                            "No URLs remaining and max_batches reached; "
                            "stopping verification loop."
                        )
                        break

                    if exit_on_idle:
                        grace = idle_grace_seconds or 0
                        if grace > 0:
                            elapsed = time.monotonic() - idle_start_monotonic
                            remaining = grace - elapsed
                            if remaining > 0:
                                if not idle_wait_logged:
                                    self.logger.info(
                                        "No URLs to verify; waiting up to %.0fs "
                                        "before exiting.",
                                        grace,
                                    )
                                    idle_wait_logged = True
                                sleep_for = min(self.sleep_interval, remaining)
                                time.sleep(max(sleep_for, 0))
                                continue

                        self.logger.info(
                            "No URLs to verify; exiting verification loop."
                        )
                        break

                    self.logger.info(
                        "No URLs to verify, sleeping for %s seconds...",
                        self.sleep_interval,
                    )
                    time.sleep(self.sleep_interval)
                    continue

                idle_start_monotonic = None
                idle_wait_logged = False

                print(
                    f"📄 Processing batch {batch_count + 1}: "
                    f"{len(candidates)} URLs..."
                )
                self.logger.info(
                    f"Processing batch {batch_count + 1} of "
                    f"{len(candidates)} URLs..."
                )

                # Process batch
                batch_metrics = self.process_batch(candidates)

                # Save telemetry
                self.save_telemetry_summary(batch_metrics, candidates, job_name)

                # Log progress to stdout and logger
                print(
                    f"✓ Batch {batch_count + 1} complete: "
                    f"{batch_metrics['verified_articles']} articles, "
                    f"{batch_metrics['verified_non_articles']} non-articles, "
                    f"{batch_metrics['verification_errors']} errors "
                    f"(avg: {batch_metrics['avg_verification_time_ms']:.1f}ms)"
                )
                self.logger.info(
                    f"Batch complete: "
                    f"{batch_metrics['verified_articles']} articles, "
                    f"{batch_metrics['verified_non_articles']} non-articles, "
                    f"{batch_metrics['verification_errors']} errors "
                    f"(avg: {batch_metrics['avg_verification_time_ms']:.1f}ms)"
                )

                batch_count += 1
                if max_batches and batch_count >= max_batches:
                    self.logger.info("Reached max batches: %s", max_batches)
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

    def get_status_summary(self) -> dict:
        """Get current status summary from the database."""
        query = """
            SELECT status, COUNT(*) as count
            FROM candidate_links
            GROUP BY status
            ORDER BY count DESC
        """

        with self.db.engine.connect() as conn:
            result = safe_execute(conn, query)
            status_counts = {row[0]: row[1] for row in result.fetchall()}

        return {
            "total_urls": sum(status_counts.values()),
            "status_breakdown": status_counts,
            "verification_pending": status_counts.get("discovered", 0),
            "articles_verified": status_counts.get("article", 0),
            "non_articles_verified": status_counts.get("not_article", 0),
            "verification_failures": status_counts.get("verification_failed", 0),
        }


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
        description="URL verification service with StorySniffer"
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
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current verification status and exit",
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
            for status_name, count in status["status_breakdown"].items():
                print(f"  {status_name}: {count}")
            return 0

        logger.info("Starting URL verification service")

        # Run verification loop
        loop_callable = service.run_verification_loop

        try:
            signature = inspect.signature(loop_callable)
        except (TypeError, ValueError):
            signature = None

        has_var_kw = False
        if signature is not None:
            params = signature.parameters
            has_var_kw = any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
            )
        else:
            params = {}

        run_kwargs: dict[str, Any] = {}

        if args.max_batches is not None and (
            signature is None or "max_batches" in params or has_var_kw
        ):
            run_kwargs["max_batches"] = args.max_batches

        if signature is None or "exit_on_idle" in params or has_var_kw:
            run_kwargs["exit_on_idle"] = True

        if run_kwargs:
            loop_callable(**run_kwargs)
        else:
            loop_callable()

        logger.info("Verification service completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Verification service failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
