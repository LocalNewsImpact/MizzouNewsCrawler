"""
Extraction command module for the modular CLI.
"""

# ruff: noqa: E501

import inspect
import json
import logging
import os
import random
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import text

# Lazy import: ContentExtractor and NotFoundError are imported inside functions
# This prevents loading the heavy src.crawler module (~150-200Mi) when not needed
from src.models import Article, CandidateLink
from src.models.database import (
    DatabaseManager,
    _commit_with_retry,
    calculate_content_hash,
    safe_session_execute,
    save_article_entities,
)

# stdlib-only module (re + collections.abc), so this stays safe to import in the
# crawler image, which carries no ML dependencies.
from src.pipeline.text_cleaning import decode_rot47_segments
from src.services.wire_detection import resolve_api_token
from src.utils.boilerplate import (
    PAYWALL,
    excise_furniture_lines,
    looks_like_furniture,
    looks_like_paywall,
)

# Lazy import: entity_extraction only needed for entity-extraction command
# Importing at top level causes ModuleNotFoundError in crawler image (no rapidfuzz)
# These are imported inside handle_entity_extraction_command() instead
# from src.pipeline.entity_extraction import (
#     ArticleEntityExtractor,
#     attach_gazetteer_matches,
#     get_gazetteer_rows,
# )
from src.utils.byline_cleaner import BylineCleaner
from src.utils.comprehensive_telemetry import (
    ComprehensiveExtractionTelemetry,
    ExtractionMetrics,
)
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner
from src.utils.content_type_detector import ContentTypeDetector
from src.utils.raw_html_archive import archive_html

# Domains known to return 403 for paywalled content (not bot blocking)
# These should be marked as 403/failed but NOT trigger a domain-wide pause
PAYWALL_DOMAINS = {
    "mdcp.nwaonline.com",
    "nwaonline.com",
}

ContentExtractor: type[Any] | None = None

# Work queue service configuration
WORK_QUEUE_URL = os.getenv(
    "WORK_QUEUE_URL", "http://work-queue.production.svc.cluster.local:8080"
)
USE_WORK_QUEUE = os.getenv("USE_WORK_QUEUE", "false").lower() == "true"

_MEDIACLOUD_TOKEN = resolve_api_token()
ENABLE_MEDIACLOUD_WIRE_CHECK = os.getenv(
    "ENABLE_WIRE_DETECTION", "true"
).lower() == "true" and bool(_MEDIACLOUD_TOKEN)

WIRE_CHECK_STATUS_PENDING = "pending"
WIRE_CHECK_STATUS_COMPLETE = "complete"
WIRE_CHECK_INITIAL_PENDING_STATUSES = {"extracted"}
WIRE_CHECK_QUEUE_STATUSES = {"cleaned", "local", "labeled"}


class _PlaceholderNotFoundError(Exception):
    """Fallback exception until crawler dependencies are loaded."""


class _PlaceholderProxyChallengeError(Exception):
    """Fallback exception until crawler dependencies are loaded."""


NotFoundError: type[Exception] = _PlaceholderNotFoundError
ProxyChallengeError: type[Exception] = _PlaceholderProxyChallengeError


def _ensure_crawler_dependencies() -> None:
    """Lazily import heavy crawler dependencies when needed."""
    global ContentExtractor, NotFoundError, ProxyChallengeError
    if ContentExtractor is None:
        from src.crawler import ContentExtractor as _ContentExtractor
        from src.crawler import NotFoundError as _NotFoundError
        from src.crawler import ProxyChallengeError as _ProxyChallengeError

        ContentExtractor = _ContentExtractor
        NotFoundError = _NotFoundError
        ProxyChallengeError = _ProxyChallengeError


logger = logging.getLogger(__name__)


def _initial_wire_check_status(article_status: str) -> str:
    """Determine the wire_check_status value for newly inserted articles.

    IMPORTANT: Default to 'pending' for all articles except those that explicitly
    don't need checking (errors, paywalls). This ensures MediaCloud verification
    runs even if article_status is set incorrectly during extraction.
    """

    if not ENABLE_MEDIACLOUD_WIRE_CHECK:
        return WIRE_CHECK_STATUS_COMPLETE

    # Only skip wire check for statuses that explicitly don't need it. A
    # not_article capture has no prose body to match against MediaCloud, so
    # checking it is pointless -- treat it like paywall/error.
    if article_status in {"error", "paywall", "obituary", "opinion", "not_article"}:
        return WIRE_CHECK_STATUS_COMPLETE

    # Default to pending for safety - includes "extracted", "wire", "cleaned", "labeled"
    # This ensures even incorrectly-set "wire" status gets verified
    return WIRE_CHECK_STATUS_PENDING


def _decode_capture(raw: str | None) -> str:
    """Decode ROT47-obfuscated body text before anything reads it as prose.

    Lee Enterprises / TownNews sites serve premium paragraphs ROT47-encoded
    rather than withholding them, so a capture looks healthy: the free preview
    is plain text and the ciphertext starts several sentences in, past the point
    where a reader — or a reviewer spot-checking the corpus — stops looking.

    The decoder itself has been in the tree and correct all along, but it was
    only ever called from two places: entity extraction, which decodes into a
    local and writes nothing back, and the standalone `clean` command. This
    module is what writes `content` and `text` for every crawled article and it
    never called it, so the ciphertext was stored and every later consumer
    inherited it. Entity extraction decoding on read is what hid the problem —
    that stage's output looked right while the cleaner, the classifier, word
    counts and the researcher export all saw scrambled text.

    Decode is applied to the CLEANING INPUT, not to the stored `content`.
    `content` keeps the raw capture verbatim so the before/after pair stays
    intact and the decode can be re-run or audited later; `text` gets the
    decoded, cleaned body.

    Returns *raw* unchanged when no ROT47 markers are present, which is the
    overwhelmingly common case.
    """

    if not raw:
        return raw or ""
    return decode_rot47_segments(raw) or raw


def _get_canonical_url(original_url: str, metadata: dict) -> str:
    """Extract canonical URL from metadata, preferring it over the original URL.

    If the canonical URL is on the same domain as the original URL, return
    the canonical URL. This helps capture wire service path indicators
    (e.g., /entertainment/cnn-style/) that may be lost when articles are
    discovered via section crawl redirects.

    Args:
        original_url: The URL used to fetch the article
        metadata: Extracted metadata dict from ContentExtractor

    Returns:
        Canonical URL if valid and same-domain, otherwise original URL
    """
    from urllib.parse import urlparse

    try:
        # Extract canonical_url from mcmetadata
        if isinstance(metadata, dict):
            mcmetadata = metadata.get("mcmetadata", {})
        else:
            mcmetadata = {}
        canonical_url = mcmetadata.get("canonical_url")

        if not canonical_url or not isinstance(canonical_url, str):
            return original_url

        canonical_url = canonical_url.strip()
        if not canonical_url:
            return original_url

        # Parse both URLs
        original_parsed = urlparse(original_url)
        canonical_parsed = urlparse(canonical_url)

        # Get domains, removing www. prefix
        original_domain = original_parsed.netloc.lower()
        canonical_domain = canonical_parsed.netloc.lower()
        if original_domain.startswith("www."):
            original_domain = original_domain[4:]
        if canonical_domain.startswith("www."):
            canonical_domain = canonical_domain[4:]

        # Only use canonical URL if it's on the same domain
        # (avoids cross-domain canonical URLs that point to wire services)
        if original_domain == canonical_domain:
            logger.debug(
                "Using canonical URL instead of original: %s → %s",
                original_url[:80],
                canonical_url[:80],
            )
            return canonical_url

        # Different domain - keep original URL
        logger.debug(
            "Canonical URL on different domain, keeping original: %s (canonical: %s)",
            original_url[:80],
            canonical_url[:80],
        )
        return original_url

    except Exception as e:
        logger.warning("Failed to extract canonical URL: %s", e)
        return original_url


def _get_worker_id() -> str:
    """Get unique worker identifier for work queue coordination.

    Returns:
        Worker ID (Kubernetes pod hostname or generated UUID)
    """
    # Use Kubernetes pod hostname
    hostname = os.getenv("HOSTNAME")
    if hostname:
        return hostname
    # Fallback for local testing
    return f"worker-{uuid.uuid4().hex[:8]}"


def _get_work_from_queue(
    worker_id: str,
    batch_size: int,
    max_articles_per_domain: int = 3,
    dataset: str | None = None,
):
    """Request work from centralized queue service with retry logic.

    Args:
        worker_id: Unique worker identifier
        batch_size: Number of articles to request
        max_articles_per_domain: Maximum articles per domain in this batch
        dataset: Dataset id to restrict work to. Without this the queue serves
            candidate links from EVERY dataset, so `extract --dataset X` would
            silently process other datasets' backlogs -- the direct-DB path
            applies the filter, the queue path did not.

    Returns:
        List of work items (dicts with id, url, source, canonical_name)

    Raises:
        Exception: If work queue request fails after all retries
    """
    import time

    import requests

    max_retries = 3
    base_timeout = 60

    for attempt in range(max_retries):
        try:
            # Increase timeout on retries (60s, 90s, 120s)
            timeout = base_timeout + (attempt * 30)

            response = requests.post(
                f"{WORK_QUEUE_URL}/work/request",
                json={
                    "worker_id": worker_id,
                    "batch_size": batch_size,
                    "max_articles_per_domain": max_articles_per_domain,
                    "dataset": dataset,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()

            if attempt > 0:
                logger.info(
                    "Work queue request succeeded on attempt %d/%d",
                    attempt + 1,
                    max_retries,
                )

            logger.info(
                "Worker %s assigned %d articles from domains: %s",
                worker_id,
                len(data["items"]),
                data.get("worker_domains", []),
            )
            return data["items"]

        except requests.RequestException as e:
            is_last_attempt = attempt == max_retries - 1

            if is_last_attempt:
                logger.error(
                    "Failed to get work from queue after %d attempts: %s",
                    max_retries,
                    e,
                )
                raise
            else:
                # Exponential backoff: 2s, 4s, 8s
                backoff = 2**attempt
                logger.warning(
                    "Work queue request failed (attempt %d/%d): %s. "
                    "Retrying in %ds...",
                    attempt + 1,
                    max_retries,
                    e,
                    backoff,
                )
                time.sleep(backoff)


def _send_heartbeat(worker_id: str):
    """Send heartbeat to work queue to prevent timeout.

    Args:
        worker_id: Worker identifier
    """
    import requests

    try:
        response = requests.post(
            f"{WORK_QUEUE_URL}/work/heartbeat",
            params={"worker_id": worker_id},
            timeout=5,
        )
        response.raise_for_status()
        logger.debug("Heartbeat sent to queue")
    except requests.RequestException as e:
        logger.debug("Failed to send heartbeat: %s", e)


def _report_domain_failure(worker_id: str, domain: str):
    """Report domain failure (rate limit/bot protection) to queue service.

    Args:
        worker_id: Worker reporting the failure
        domain: Domain that failed
    """
    import requests

    try:
        response = requests.post(
            f"{WORK_QUEUE_URL}/work/report-failure",
            params={"worker_id": worker_id, "domain": domain},
            timeout=10,
        )
        response.raise_for_status()
        logger.info("Reported domain failure to queue: %s", domain)
    except requests.RequestException as e:
        logger.warning("Failed to report domain failure: %s", e)


def _to_int(value, default=0):
    """Convert PostgreSQL string or SQLite int to int.

    PostgreSQL returns aggregate results as strings, SQLite returns native types.
    This helper ensures consistent int conversion across both databases.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _attach_driver_metrics(
    metrics: ExtractionMetrics,
    extractor: Any,
    domain: str | None,
):
    """Attach driver/proxy telemetry snapshot to the current metrics object."""

    if not metrics or not extractor:
        return

    snapshot = None
    try:
        snapshot = extractor.get_driver_telemetry_snapshot(domain)
    except AttributeError:
        return
    except Exception:
        logger.exception("Failed to capture driver telemetry snapshot")
        return

    if snapshot:
        metrics.set_driver_metrics(snapshot)


_ENTITY_EXTRACTOR: Any = None  # ArticleEntityExtractor lazy loaded
_CONTENT_TYPE_DETECTOR: ContentTypeDetector | None = None


def _get_entity_extractor() -> Any:  # Returns ArticleEntityExtractor
    """Lazy load entity extractor (requires rapidfuzz in processor image)."""
    global _ENTITY_EXTRACTOR
    if _ENTITY_EXTRACTOR is None:
        from src.pipeline.entity_extraction import ArticleEntityExtractor

        _ENTITY_EXTRACTOR = ArticleEntityExtractor()
    return _ENTITY_EXTRACTOR


def _get_content_type_detector() -> ContentTypeDetector:
    global _CONTENT_TYPE_DETECTOR
    if _CONTENT_TYPE_DETECTOR is None:
        _CONTENT_TYPE_DETECTOR = ContentTypeDetector()
    return _CONTENT_TYPE_DETECTOR


def _capture_raw_html(extractor: Any) -> tuple[str | bytes | None, str | None]:
    """Return ``(html, method)`` for archiving, or ``(None, None)``.

    Not every object passed in here is a full ContentExtractor — tests and
    alternate paths supply lighter stand-ins. Archiving is best-effort, so a
    stand-in that can't provide HTML must cost us nothing. ContentExtractor
    always decodes to ``str``; ``bytes`` is tolerated for stand-ins that don't,
    since ``archive_html`` encodes either.
    """
    getter = getattr(extractor, "get_last_raw_html", None)
    if not callable(getter):
        return None, None
    try:
        html, method = getter()
    except Exception:
        # Includes stand-ins whose attribute access auto-returns something
        # unpackable-looking; unpacking here keeps that out of the caller.
        logger.debug("Extractor could not provide raw HTML", exc_info=True)
        return None, None

    if not isinstance(html, (str, bytes)):
        return None, None
    return html, method if isinstance(method, str) else None


ARTICLE_INSERT_SQL = text(
    "INSERT INTO articles (id, candidate_link_id, url, title, author, "
    "publish_date, content, text, status, metadata, wire, wire_check_status, "
    "wire_check_attempted_at, wire_check_error, wire_check_metadata, extracted_at, "
    "created_at, text_hash, raw_gcs_path) VALUES (:id, :candidate_link_id, :url, :title, "
    ":author, :publish_date, :content, :text, :status, :metadata, :wire, "
    ":wire_check_status, :wire_check_attempted_at, :wire_check_error, :wire_check_metadata, "
    ":extracted_at, :created_at, :text_hash, :raw_gcs_path) "
    # Avoid specifying a conflict target here (ON CONFLICT (url) ...) if the
    # corresponding unique constraint may not exist in some deployments. Using
    # a plain DO NOTHING will avoid raising InvalidColumnReference while still
    # allowing PostgreSQL to skip inserts when a relevant unique constraint is
    # present. To enforce deduplication permanently, add a UNIQUE constraint on
    # `articles.url` in the DB (see migration instructions in the logs).
    "ON CONFLICT DO NOTHING"
)

CANDIDATE_STATUS_UPDATE_SQL = text(
    "UPDATE candidate_links SET status = :status WHERE id = :id"
)

PAUSE_CANDIDATE_LINKS_SQL = text(
    "UPDATE candidate_links "
    "SET status = :status, error_message = :error "
    "WHERE url LIKE :host_like OR source = :host"
)

# `content` is deliberately absent: it is the canonical capture and is never
# written after insert. This statement used to carry "content = :content" bound
# to original_content -- the value it had just SELECTed -- so dropping it is a
# no-op today and makes the column immutable by construction rather than by
# every caller remembering to pass the value back unchanged.
ARTICLE_UPDATE_SQL = text(
    "UPDATE articles SET text = :text, "
    "text_hash = :text_hash, text_excerpt = :excerpt, status = :status "
    "WHERE id = :id"
)

ARTICLE_STATUS_UPDATE_SQL = text("UPDATE articles SET status = :status WHERE id = :id")

ARTICLE_MARK_WIRE_PENDING_SQL = text(
    "UPDATE articles SET wire_check_status = 'pending', wire_check_attempted_at = NULL, "
    "wire_check_error = NULL, wire_check_metadata = NULL WHERE id = :id"
)

ARTICLE_MARK_WIRE_COMPLETE_SQL = text(
    "UPDATE articles SET wire_check_status = 'complete', wire_check_error = NULL WHERE id = :id"
)


def _format_cleaned_authors(authors):
    """Convert a list of cleaned author names into a display string."""
    if not authors:
        return None

    normalized = [author.strip() for author in authors if author and author.strip()]
    if not normalized:
        return None

    return ", ".join(normalized)


def _get_status_counts(args, session):
    """Get counts of candidate links by status for the current dataset/source.

    Args:
        args: Command arguments containing dataset/source filters
        session: Database session

    Returns:
        dict mapping status -> count (e.g., {'article': 207, 'extracted': 4445, ...})
    """
    query = """
    SELECT cl.status, COUNT(*) as count
    FROM candidate_links cl
    WHERE 1=1
    """

    params = {}

    # Add dataset filter if specified (dataset is already resolved to UUID)
    if getattr(args, "dataset", None):
        query += " AND cl.dataset_id = :dataset"
        params["dataset"] = args.dataset
    # NOTE: Removed cron_enabled filter - was blocking all extractions

    # Add source filter if specified
    if getattr(args, "source", None):
        query += " AND cl.source = :source"
        params["source"] = args.source

    query += " GROUP BY cl.status ORDER BY count DESC"

    try:
        result = safe_session_execute(session, query, params)
        return {row[0]: row[1] for row in result.fetchall()}
    except Exception as e:
        logger.warning("Failed to get status counts: %s", e)
        return {}


def _analyze_dataset_domains(args, session):
    """Analyze how many unique domains exist in the dataset's candidate links.

    Args:
        args: Command arguments containing dataset/source filters
        session: Database session

    Returns:
        dict with keys:
            - unique_domains: int, number of unique domains
            - is_single_domain: bool, whether dataset has only one domain
            - sample_domains: list of up to 5 sample domain names
    """
    from urllib.parse import urlparse

    # Build query to get candidate links for this dataset/candidate links
    # Optimized: NOT EXISTS is 20-40x faster than NOT IN (avoids subquery materialization)
    query = """
    SELECT DISTINCT cl.url
    FROM candidate_links cl
    LEFT JOIN sources s ON cl.source_id = s.id
    WHERE cl.status = 'article'
    AND (s.status IS NULL OR s.status = 'active')
    AND NOT EXISTS (
        SELECT 1 FROM articles a
        WHERE a.candidate_link_id = cl.id
    )
    """

    params = {}

    # Add dataset filter if specified (dataset is already resolved to UUID)
    if getattr(args, "dataset", None):
        query += " AND cl.dataset_id = :dataset"
        params["dataset"] = args.dataset
    # NOTE: Removed cron_enabled filter - was blocking all extractions

    # Add source filter if specified
    if getattr(args, "source", None):
        query += " AND cl.source = :source"
        params["source"] = args.source

    query += " LIMIT 1000"  # Sample up to 1000 URLs for analysis

    try:
        result = safe_session_execute(session, text(query), params)
        urls = [row[0] for row in result.fetchall()]

        if not urls:
            return {
                "unique_domains": 0,
                "is_single_domain": False,
                "sample_domains": [],
            }

        # Extract domains from URLs
        domains = set()
        for url in urls:
            try:
                domain = urlparse(url).netloc
                if domain:
                    domains.add(domain)
            except Exception:
                continue

        unique_count = len(domains)
        sample_list = sorted(domains)[:5]

        return {
            "unique_domains": unique_count,
            "is_single_domain": unique_count == 1,
            "sample_domains": sample_list,
        }
    except Exception as e:
        logger.warning(f"Failed to analyze dataset domains: {e}")
        return {
            "unique_domains": 0,
            "is_single_domain": False,
            "sample_domains": [],
        }


def add_extraction_parser(subparsers):
    """Add extraction command parser to CLI."""
    extract_parser = subparsers.add_parser(
        "extract", help="Extract content from verified articles"
    )
    extract_parser.add_argument(
        "--limit", type=int, default=10, help="Articles per batch"
    )
    extract_parser.add_argument(
        "--batches",
        type=int,
        default=None,
        help="Number of batches (default: process all available)",
    )
    extract_parser.add_argument(
        "--source",
        type=str,
        help="Limit to a specific source",
    )
    extract_parser.add_argument(
        "--dataset",
        type=str,
        help="Limit to a specific dataset slug",
    )
    extract_parser.add_argument(
        "--no-exhaust-queue",
        dest="exhaust_queue",
        action="store_false",
        default=True,
        help="Stop after --batches instead of processing all available articles",
    )
    extract_parser.add_argument(
        "--dump-sql",
        dest="dump_sql",
        action="store_true",
        default=False,
        help="Dump SQL statements and parameters before executing (diagnostic)",
    )
    extract_parser.add_argument(
        "--verify-insert",
        dest="verify_insert",
        action="store_true",
        default=False,
        help=(
            "After committing an inserted article, run a SELECT to verify the "
            "row exists and log a mismatch (diagnostic)."
        ),
    )
    extract_parser.add_argument(
        "--selenium-mode",
        choices=("headful", "headless"),
        help=(
            "Override SELENIUM_EXECUTION_MODE for this run. "
            "Defaults to the environment variable or 'headful' when unset."
        ),
    )

    extract_parser.set_defaults(func=handle_extraction_command)


def _set_proxy_env_safety_net() -> None:
    """Point stray third-party fetchers at the proxy via env vars.

    The session/router paths carry their own proxies explicitly; this is
    the backstop for any library that opens its own connection (newspaper4k
    internals, feedparser, future dependencies). Discovery has done the
    same since day one (_set_global_proxy_env); extraction never did --
    which is how mcmetadata's built-in fetcher, the week it went live as
    the primary extractor, egressed directly from the pod IP with no test
    or telemetry noticing.

    NO_PROXY exempts cluster-internal services (work-queue), Google APIs
    (Firestore/GCS/Cloud SQL admin), and the metadata server -- proxying
    those through a residential Squid would break them.
    """
    proxy_url = os.getenv("SQUID_PROXY_URL")
    if not proxy_url:
        return

    no_proxy = (
        "localhost,127.0.0.1,169.254.169.254,metadata.google.internal,"
        ".svc.cluster.local,.googleapis.com,.google.com"
    )
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.setdefault(key, proxy_url)
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(key)
        os.environ[key] = f"{existing},{no_proxy}" if existing else no_proxy
    logger.info("🌍 Proxy env safety net set for third-party libraries")


def handle_extraction_command(args) -> int:
    """Execute extraction command logic."""
    _ensure_crawler_dependencies()
    if ContentExtractor is None:  # pragma: no cover - defensive fallback
        raise RuntimeError("ContentExtractor dependency is unavailable")

    _set_proxy_env_safety_net()

    extractor_cls = ContentExtractor
    process_accepts_db = "db" in inspect.signature(_process_batch).parameters
    post_clean_accepts_db = (
        "db" in inspect.signature(_run_post_extraction_cleaning).parameters
    )
    batches = getattr(args, "batches", None)  # None means "process all available"
    per_batch = getattr(args, "limit", 10)
    exhaust_queue = getattr(args, "exhaust_queue", True)  # Default to exhausting queue

    # Print to stdout immediately for visibility
    print("🚀 Starting content extraction...")
    if batches is None or exhaust_queue:
        print("   Mode: Process ALL available articles")
    else:
        print(f"   Batches: {batches}")
    print(f"   Articles per batch: {per_batch}")

    # Create DatabaseManager early to analyze dataset
    try:
        db = DatabaseManager()
    except Exception:
        logger.exception("Failed to initialize database connection")
        return 1

    # Resolve dataset parameter to UUID for consistent querying
    dataset_uuid = None
    if getattr(args, "dataset", None):
        try:
            from src.utils.dataset_utils import resolve_dataset_id

            dataset_uuid = resolve_dataset_id(db.engine, args.dataset)
            logger.info(
                "Resolved dataset '%s' to UUID: %s",
                args.dataset,
                dataset_uuid,
            )
            print(f"   Dataset: {args.dataset} (UUID: {dataset_uuid})")
            # Replace args.dataset with resolved UUID for downstream code
            args.dataset = dataset_uuid
        except ValueError as e:
            logger.error("Dataset resolution failed: %s", e)
            print(f"❌ Error: {e}")
            return 1

    # Analyze dataset domain structure upfront
    domain_analysis = _analyze_dataset_domains(args, db.session)
    if domain_analysis["unique_domains"] > 0:
        print(
            "   📊 Dataset analysis: "
            f"{domain_analysis['unique_domains']} unique domain(s)"
        )
        if domain_analysis["is_single_domain"]:
            print(
                "   ⚠️  Single-domain dataset detected: "
                f"{domain_analysis['sample_domains'][0]}"
            )
            print("   🐌 Rate limiting will be conservative to avoid bot detection")
            # Recommend appropriate BATCH_SLEEP_SECONDS for single-domain datasets
            batch_sleep = float(os.getenv("BATCH_SLEEP_SECONDS", "0.1"))
            if batch_sleep < 60:
                logger.warning(
                    "Single-domain dataset detected but BATCH_SLEEP_SECONDS is low "
                    "(%.1fs). Consider increasing to 60-300s to avoid rate limiting.",
                    batch_sleep,
                )
        elif domain_analysis["unique_domains"] <= 3:
            print(
                "   ⚠️  Limited domain diversity "
                f"({domain_analysis['unique_domains']} domains)"
            )
            print(f"   Sample domains: {', '.join(domain_analysis['sample_domains'])}")
        else:
            print("   ✓ Good domain diversity for rotation")
            if domain_analysis["unique_domains"] <= 10:
                print(
                    f"   Sample domains: {', '.join(domain_analysis['sample_domains'])}"
                )
    print()

    extractor_kwargs = {}
    cli_selenium_mode = getattr(args, "selenium_mode", None)
    if cli_selenium_mode:
        extractor_kwargs["selenium_mode"] = cli_selenium_mode

    extractor = extractor_cls(**extractor_kwargs)
    env_selenium_mode = os.getenv("SELENIUM_EXECUTION_MODE")
    effective_selenium_mode = getattr(
        extractor,
        "selenium_mode",
        cli_selenium_mode or env_selenium_mode or "headful",
    )
    if cli_selenium_mode:
        selenium_mode_source = "CLI override"
    elif env_selenium_mode:
        selenium_mode_source = "environment"
    else:
        selenium_mode_source = "default"
    print("   Selenium mode: " f"{effective_selenium_mode} ({selenium_mode_source})")
    logger.info(
        "Extractor initialized with Selenium mode %s (source=%s)",
        effective_selenium_mode,
        selenium_mode_source,
    )
    byline_cleaner = BylineCleaner()
    content_cleaner = BalancedBoundaryContentCleaner(
        enable_telemetry=False  # Don't need telemetry for validation-only cleaning
    )
    telemetry = ComprehensiveExtractionTelemetry()

    # Track hosts that return 403 responses within this run
    # Use defaultdict(int) so callers can increment without extra checks
    # and to provide an explicit typed container for static checks.
    host_403_tracker: dict[str, int] = defaultdict(int)

    try:
        domains_for_cleaning: dict[str, list[str]] = defaultdict(list)
        batch_num = 0
        total_processed = 0

        # Store whether we detected single-domain dataset
        is_single_domain_dataset = domain_analysis.get("is_single_domain", False)

        # Continue processing batches until no articles remain
        # (or the batch limit is reached when explicitly requested)
        while True:
            batch_num += 1

            # If batches specified and exhaust_queue is False, respect the limit
            if batches is not None and not exhaust_queue and batch_num > batches:
                break

            # Apply batch size jitter when configured
            # (e.g., BATCH_SIZE_JITTER=0.33 means ±33%)
            batch_size_jitter = float(os.getenv("BATCH_SIZE_JITTER", "0.0"))
            if batch_size_jitter > 0:
                jitter_amount = int(per_batch * batch_size_jitter)
                batch_size = max(
                    1,
                    per_batch + random.randint(-jitter_amount, jitter_amount),
                )
            else:
                batch_size = per_batch

            print(f"📄 Processing batch {batch_num} ({batch_size} articles)...")
            process_kwargs = {"db": db} if process_accepts_db else {}
            result = _process_batch(
                args,
                extractor,
                byline_cleaner,
                content_cleaner,
                telemetry,
                batch_size,
                batch_num,
                host_403_tracker,
                domains_for_cleaning,
                **process_kwargs,
            )

            articles_processed = result["processed"]
            total_processed += articles_processed

            # Log batch completion with status counts (skip expensive remaining count)
            # The remaining count query was causing 20+ minute delays due to
            # expensive LEFT JOIN even with proper indexing
            try:
                db.session.expire_all()
                db.session.commit()

                # Get status breakdown (fast GROUP BY query)
                status_counts = _get_status_counts(args, db.session)
                remaining_estimate = status_counts.get("article", "?")

                print(
                    f"✓ Batch {batch_num} complete: {articles_processed} "
                    f"articles extracted (~{remaining_estimate} remaining)"
                )

                if status_counts:
                    key_statuses = [
                        "article",
                        "extracted",
                        "wire",
                        "obituary",
                        "opinion",
                    ]
                    status_parts = []
                    for status in key_statuses:
                        if status in status_counts:
                            count_str = f"{status}={status_counts[status]:,}"
                            status_parts.append(count_str)

                    if status_parts:
                        print(f"  📊 Status breakdown: {', '.join(status_parts)}")
                        status_dict = {
                            k: v for k, v in status_counts.items() if k in key_statuses
                        }
                        logger.info(
                            "Batch %d status counts: %s", batch_num, status_dict
                        )

            except Exception as e:
                logger.warning("Failed to get status counts: %s", e)
                print(
                    f"✓ Batch {batch_num} complete: "
                    f"{articles_processed} articles extracted"
                )

            if result.get("skipped_domains", 0) > 0:
                print(
                    f"  ⚠️  {result['skipped_domains']} domains "
                    f"skipped due to rate limits"
                )
            logger.info(f"Batch {batch_num}: {result}")

            # Stop if no articles were processed
            if articles_processed == 0:
                if USE_WORK_QUEUE:
                    # In work queue mode, no articles means all domains are
                    # in cooldown or assigned to other workers. Wait and retry.
                    retry_delay = int(os.getenv("WORK_QUEUE_RETRY_DELAY", "30"))
                    print(
                        f"⏳ No articles available - all domains in cooldown. "
                        f"Retrying in {retry_delay}s..."
                    )
                    logger.info(
                        "Work queue returned 0 articles - "
                        "domains in cooldown, will retry"
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    # In direct query mode, no articles means database exhausted
                    print("📭 No more articles available to extract")
                    break

            # Smart batch sleep: pause when we repeatedly hit the same domain.
            # When domains rotate, per-domain rate limiting avoids the need to pause.
            domains_processed = result.get("domains_processed", [])
            same_domain_consecutive = result.get("same_domain_consecutive", 0)
            unique_domains = len(set(domains_processed)) if domains_processed else 0
            skipped_domains = result.get("skipped_domains", 0)

            # Apply long batch sleep if:
            # 1. Dataset was pre-identified as single-domain (most reliable)
            # 2. Same domain hit repeatedly (exhausted rotation), OR
            # 3. Only one domain in entire batch (single-domain dataset)
            max_same_domain = int(os.getenv("MAX_SAME_DOMAIN_CONSECUTIVE", "3"))
            is_single_domain_dataset = unique_domains <= 1 and skipped_domains == 0
            needs_long_pause = (
                is_single_domain_dataset
                or same_domain_consecutive >= max_same_domain
                or unique_domains <= 1
            )

            if needs_long_pause:
                batch_sleep = float(os.getenv("BATCH_SLEEP_SECONDS", "0.1"))
                if batch_sleep > 0:
                    # Apply jitter to batch sleep
                    batch_jitter = float(os.getenv("BATCH_SLEEP_JITTER", "0.0"))
                    if batch_jitter > 0:
                        # keep jitter_amount as int to match earlier usage
                        jitter_amount = int(batch_sleep * batch_jitter)
                        actual_sleep = random.uniform(
                            batch_sleep - jitter_amount, batch_sleep + jitter_amount
                        )
                    else:
                        actual_sleep = batch_sleep

                    # Determine reason for long pause
                    if is_single_domain_dataset:
                        reason = "single-domain dataset"
                    elif same_domain_consecutive >= max_same_domain:
                        reason = f"same domain hit {same_domain_consecutive} times"
                    else:
                        reason = "single-domain batch"

                    print(
                        f"   ⏸️  {reason.capitalize()} - waiting {actual_sleep:.0f}s..."
                    )
                    time.sleep(actual_sleep)
            elif unique_domains > 1 or skipped_domains > 0:
                # Rotated through multiple domains or these domains remained available,
                # so a brief pause is sufficient even if some were rate limited.
                short_pause = float(os.getenv("INTER_BATCH_MIN_PAUSE", "5.0"))
                if skipped_domains > 0:
                    print(
                        f"   ✓ Multiple domains available "
                        f"({skipped_domains} rate-limited) - "
                        f"minimal {short_pause:.0f}s pause"
                    )
                else:
                    print(
                        f"   ✓ Rotated through {unique_domains} domains - "
                        f"minimal {short_pause:.0f}s pause"
                    )
                time.sleep(short_pause)
            else:
                # Fallback: short pause
                short_pause = float(os.getenv("INTER_BATCH_MIN_PAUSE", "5.0"))
                time.sleep(short_pause)

        if domains_for_cleaning:
            print()
            print(
                "🧹 Running post-extraction cleaning for "
                f"{len(domains_for_cleaning)} domains..."
            )
            post_clean_kwargs = {"db": db} if post_clean_accepts_db else {}
            _run_post_extraction_cleaning(domains_for_cleaning, **post_clean_kwargs)
            print("✓ Cleaning complete")

        # Log driver usage stats before cleanup
        driver_stats = extractor.get_driver_stats()
        if driver_stats["has_persistent_driver"]:
            print()
            print(
                "📊 ChromeDriver efficiency: "
                f"{driver_stats['driver_reuse_count']} reuses, "
                f"{driver_stats['driver_creation_count']} creations"
            )
            logger.info(
                "ChromeDriver efficiency: %s reuses, %s creations",
                driver_stats["driver_reuse_count"],
                driver_stats["driver_creation_count"],
            )

        print()
        print("✅ Extraction completed successfully!")
        print(f"   Total batches processed: {batch_num}")
        print(f"   Total articles extracted: {total_processed}")
        return 0
    except Exception:
        logger.exception("Extraction failed")
        return 1
    finally:
        # Clean up persistent driver when job is complete
        extractor.close_persistent_driver()


def handle_extract_url_command(args) -> int:
    """Extract a single URL and persist the result to the database.

    This mirrors the extraction flow used by the batch processor but focuses
    on a single candidate URL for quick debugging and operational checks.
    """
    _ensure_crawler_dependencies()
    if ContentExtractor is None:
        raise RuntimeError("ContentExtractor dependency is unavailable")

    url = getattr(args, "url", None)
    if not url:
        print("❌ Error: No URL provided")
        return 1

    # Basic URL sanity check
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        print("❌ Error: Invalid URL")
        return 1

    try:
        db = DatabaseManager()
    except Exception:
        logger.exception("Failed to initialize database connection")
        return 1

    session = db.session
    try:
        # Find or create candidate link record
        candidate = session.query(CandidateLink).filter_by(url=url).one_or_none()
        if candidate is None:
            candidate = CandidateLink(
                url=url,
                source=getattr(args, "source", parsed.netloc),
                status="article",
                discovered_by="extract-url",
                dataset_id=getattr(args, "dataset", None),
            )
            session.add(candidate)
            session.commit()
            logger.info("Created candidate link for URL: %s", url)

        # Prevent duplicate extraction if an article already exists for this link
        existing = (
            session.query(Article)
            .filter(Article.candidate_link_id == candidate.id)
            .first()
        )
        if existing:
            print(f"⚠️  Article already exists for URL: {url} (id={existing.id})")
            return 0

        extractor = ContentExtractor(selenium_mode=getattr(args, "selenium_mode", None))
        byline_cleaner = BylineCleaner()
        content_cleaner = BalancedBoundaryContentCleaner(enable_telemetry=False)

        article_id = str(uuid.uuid4())
        # Normalize publisher to a plain string for metrics and avoid SQLAlchemy types
        publisher = (
            str(candidate.source)
            if candidate.source
            else (
                str(candidate.source_name) if candidate.source_name else parsed.netloc
            )
        )
        operation_id = f"ext_url_{article_id}"
        metrics = ExtractionMetrics(operation_id, article_id, url, publisher)

        print(f"🔍 Extracting {url}... (candidate id: {candidate.id})")
        content = extractor.extract_content(url, metrics=metrics)
        if not content or not content.get("title"):
            logger.warning("No content or title extracted for %s", url)
            print("⚠️  No content extracted (title missing)")
            return 1

        # Run byline cleaning and wire hints detection (simplified)
        raw_author = content.get("author")
        cleaned_author = None
        if raw_author:
            # Ensure source_name is a plain string for BylineCleaner
            source_name_arg = str(candidate.source) if candidate.source else None
            byline_result = byline_cleaner.clean_byline(
                raw_author, return_json=True, source_name=source_name_arg
            )
            cleaned_author = _format_cleaned_authors(byline_result.get("authors", []))

        # Basic wire detection via mcmetadata hints
        metadata_value = content.get("metadata") or {}
        wire_service_info = None
        article_status = "extracted"
        wire_hints = metadata_value.get("wire_hints")
        if isinstance(wire_hints, dict):
            hint_services = [svc for svc in wire_hints.get("wire_services", []) if svc]
            if hint_services:
                article_status = "wire"
                wire_service_info = json.dumps(hint_services)

        # Content cleaning and text hash calculation
        domain = parsed.netloc
        content_text = content.get("content") or content.get("text") or ""
        if not content_text or len(content_text.strip()) == 0:
            print("⚠️  Extracted content is empty")
            return 1

        # If necessary, run content cleaning to obtain text
        decoded_text = _decode_capture(content_text)
        try:
            cleaned_text, _cleaned_meta = content_cleaner.process_single_article(
                decoded_text, domain, dry_run=False
            )
        except Exception:
            cleaned_text = decoded_text
            _cleaned_meta = {}

        text_hash = calculate_content_hash(cleaned_text)
        now = datetime.utcnow()

        # Insert article row
        wire_check_status = _initial_wire_check_status(article_status)

        # Prefer canonical URL if available (preserves wire path indicators)
        article_url = _get_canonical_url(url, metadata_value)

        raw_html, raw_html_method = _capture_raw_html(extractor)
        raw_gcs_path = archive_html(article_url, raw_html, article_id, raw_html_method)

        try:
            safe_session_execute(
                session,
                ARTICLE_INSERT_SQL,
                {
                    "id": article_id,
                    "candidate_link_id": str(candidate.id),
                    "url": article_url,
                    "title": content.get("title"),
                    "author": cleaned_author,
                    "publish_date": content.get("publish_date"),
                    # content holds the RAW capture, text the cleaned body.
                    # These used to receive the same cleaned string, which threw
                    # the raw copy away: `content` was byte-identical to `text`
                    # for 96,169 of 96,170 stored articles. With no before/after
                    # pair, nothing could measure what cleaning removed — or
                    # notice that it had stopped removing anything.
                    # The rest of the pipeline already assumes this split:
                    # cleaning reads a.content as its input, entity extraction
                    # reads a.text as the cleaned result.
                    "content": content_text,
                    "text": cleaned_text,
                    "status": article_status,
                    "metadata": json.dumps(metadata_value),
                    "wire": wire_service_info,
                    "wire_check_status": wire_check_status,
                    "wire_check_attempted_at": None,
                    "wire_check_error": None,
                    "wire_check_metadata": None,
                    "extracted_at": now.isoformat(),
                    "created_at": now.isoformat(),
                    "text_hash": text_hash,
                    "raw_gcs_path": raw_gcs_path,
                },
            )

            # Update candidate_link status to reflect extraction outcome
            safe_session_execute(
                session,
                CANDIDATE_STATUS_UPDATE_SQL,
                {"status": article_status, "id": str(candidate.id)},
            )

            # Optionally verify insert
            if getattr(args, "verify_insert", False):
                row = safe_session_execute(
                    session,
                    text("SELECT id, url FROM articles WHERE id = :id"),
                    {"id": article_id},
                ).fetchone()
                if not row:
                    logger.warning(
                        "Inserted article not found via verification select: %s",
                        article_id,
                    )

            session.commit()
            print(
                f"✅ Article extracted & saved: {article_id} (status={article_status})"
            )
        except Exception as insert_error:
            logger.exception("Failed to insert article for %s: %s", url, insert_error)
            session.rollback()
            return 1

        # Trigger post-extraction cleaning + entity extraction for the saved article
        domains_for_cleaning = {domain: [article_id]}
        _run_post_extraction_cleaning(domains_for_cleaning, db=session)

        return 0
    finally:
        try:
            extractor.close_persistent_driver()
        except Exception:
            pass


# Note: `extract-url` command now lives in src/cli/commands/extract_url.py.
# The handler function `handle_extract_url_command` is exported here for
# convenience so other modules may import it directly.


def _process_batch(
    args,
    extractor,
    byline_cleaner,
    content_cleaner,
    telemetry,
    per_batch,
    batch_num,
    host_403_tracker,
    domains_for_cleaning,
    db=None,
):
    """Process a single extraction batch with domain-aware rate limiting.

    Note: content_cleaner can be any object with a process_single_article(text, domain, dry_run=False)
    method that returns (cleaned_text, metadata).
    """
    """Process a single extraction batch with domain-aware rate limiting."""
    if db is None:
        db = DatabaseManager()
    session = db.session

    # Track domain failures and articles processed per domain in this batch
    domain_failures = {}  # domain -> consecutive_failures
    domain_article_count = {}  # domain -> articles_processed_in_batch
    domains_processed = []  # ordered list of domains processed
    last_domain = None
    same_domain_consecutive = 0
    max_failures_per_domain = 2
    max_articles_per_domain = int(os.getenv("MAX_ARTICLES_PER_DOMAIN_PER_BATCH", "3"))

    # Heartbeat tracking for work-queue coordination
    last_heartbeat = time.time()
    heartbeat_interval = 300  # Send heartbeat every 5 minutes
    worker_id = None  # Will be set if using work queue

    try:
        # Get candidate articles - either from work queue service or direct DB query
        if USE_WORK_QUEUE:
            # Use centralized work queue for domain-aware coordination
            worker_id = _get_worker_id()
            logger.info("📡 Requesting work from queue service as %s", worker_id)

            work_items = _get_work_from_queue(
                worker_id=worker_id,
                batch_size=per_batch,
                max_articles_per_domain=max_articles_per_domain,
                dataset=getattr(args, "dataset", None),
            )

            if not work_items:
                logger.warning("⚠️  No work available from queue service")
                return {"processed": 0}

            # Convert work items to row format expected by extraction loop
            rows = [
                (
                    item["id"],
                    item["url"],
                    item["source"],
                    "article",
                    item.get("canonical_name"),
                )
                for item in work_items
            ]
        else:
            # Direct database query (original logic, used when work queue disabled)
            # Get articles with domain diversity to avoid rate-limit lockups
            q = """
            SELECT cl.id, cl.url, cl.source, cl.status, s.canonical_name
            FROM candidate_links cl
            LEFT JOIN sources s ON cl.source_id = s.id
            WHERE cl.status = 'article'
            AND NOT EXISTS (
                SELECT 1 FROM articles a
                WHERE a.candidate_link_id = cl.id
            )
            AND (s.status IS NULL OR s.status = 'active')
            ORDER BY RANDOM()  -- Use random order to mix domains
            LIMIT :limit_with_buffer
            """

            # Request more articles than we need to allow for domain skipping
            buffer_multiplier = 3
            params = {"limit_with_buffer": per_batch * buffer_multiplier}

            # Add dataset filter if specified (dataset is already resolved to UUID)
            if getattr(args, "dataset", None):
                q = q.replace(
                    "WHERE cl.status = 'article'",
                    """WHERE cl.status = 'article'
                    AND cl.dataset_id = :dataset""",
                )
                params["dataset"] = args.dataset
                logger.info(
                    "🔍 Extraction query filtering by dataset: %s", args.dataset
                )
            # NOTE: Removed cron_enabled filter - was blocking all extractions
            # All candidate_links with status='article' are fair game

            # Add source filter if specified
            if getattr(args, "source", None):
                if "cl.dataset_id" in q:
                    q = q.replace(
                        "AND cl.dataset_id",
                        "AND cl.source = :source AND cl.dataset_id",
                    )
                else:
                    q = q.replace(
                        "WHERE cl.status = 'article'",
                        "WHERE cl.status = 'article' AND cl.source = :source",
                    )
                params["source"] = args.source

            # Add row-level locking for parallel processing (PostgreSQL only)
            # SKIP LOCKED allows multiple workers to process different rows simultaneously
            # SQLite doesn't support FOR UPDATE, so skip it for e2e/unit tests
            try:
                dialect_name = session.bind.dialect.name if session.bind else None
            except AttributeError:
                # Mock session in tests
                dialect_name = None

            if dialect_name == "postgresql":
                q += " FOR UPDATE OF cl SKIP LOCKED"

            result = safe_session_execute(session, text(q), params)
            rows = result.fetchall()
            logger.info(
                "🔍 Extraction query returned %d candidate articles (requested: %d)",
                len(rows),
                params["limit_with_buffer"],
            )
            if not rows:
                logger.warning("⚠️  No articles found matching extraction criteria")
                return {"processed": 0}

        processed = 0
        skipped_domains = set()

        for row in rows:
            # Send heartbeat to work queue if enough time has passed
            if (
                USE_WORK_QUEUE
                and worker_id
                and (time.time() - last_heartbeat) > heartbeat_interval
            ):
                _send_heartbeat(worker_id)
                last_heartbeat = time.time()

            # Stop if we've processed enough articles
            if processed >= per_batch:
                break

            url_id, url, source, status, canonical_name = row

            # Extract domain for failure tracking
            from urllib.parse import urlparse

            domain = urlparse(url).netloc

            # Skip domains that already hit the per-batch limit
            current_domain_count = domain_article_count.get(domain, 0)
            if current_domain_count >= max_articles_per_domain:
                logger.debug(
                    "Skipping %s - domain %s hit max %d articles per batch",
                    url,
                    domain,
                    max_articles_per_domain,
                )
                continue

            # Skip domains that have failed too many times
            if domain in skipped_domains:
                logger.debug(
                    "Skipping %s - domain %s temporarily blocked",
                    url,
                    domain,
                )
                continue

            # Check if domain is currently rate limited by extractor (CAPTCHA backoff)
            if extractor._check_rate_limit(domain):
                logger.info(
                    "Skipping %s - domain %s is rate limited (backoff active)",
                    url,
                    domain,
                )
                skipped_domains.add(domain)
                continue

            operation_id = f"ex_{batch_num}_{url_id}"
            article_id = str(uuid.uuid4())
            publisher = canonical_name or source
            metrics = ExtractionMetrics(
                operation_id,
                article_id,
                url,
                publisher,
            )

            try:
                content = extractor.extract_content(url, metrics=metrics)
                detection_payload = None

                # Check for proxy/bot challenge page before processing
                if content and content.get("title"):
                    title = content.get("title", "")
                    content_text = content.get("content", "")

                    # Proxy challenge patterns
                    proxy_patterns = [
                        "Access to this page has been denied",
                        "Attention Required",
                        "Just a moment",
                        "Please verify you are a human",
                        "Checking your browser",
                        "Access Denied",
                    ]

                    is_proxy_challenge = any(
                        pattern in title
                        or (content_text and pattern in content_text[:500])
                        for pattern in proxy_patterns
                    )

                    if is_proxy_challenge:
                        logger.warning(
                            "🚫 Proxy/bot challenge detected for %s (title: %s)",
                            url,
                            title[:100],
                        )
                        # Mark as failed and skip this URL
                        try:
                            safe_session_execute(
                                session,
                                CANDIDATE_STATUS_UPDATE_SQL,
                                {"status": "proxy_blocked", "id": str(url_id)},
                            )
                            session.commit()
                        except Exception:
                            logger.exception("Failed to mark URL as proxy_blocked")
                            session.rollback()

                        error_msg = f"Proxy challenge detected: {title[:100]}"
                        metrics.error_message = error_msg
                        metrics.error_type = "proxy_blocked"
                        _attach_driver_metrics(metrics, extractor, domain)
                        metrics.finalize(content)
                        telemetry.record_extraction(metrics)
                        continue

                if content and content.get("title"):
                    # Track successful extraction from this domain
                    domain_article_count[domain] = (
                        domain_article_count.get(domain, 0) + 1
                    )

                    # Track domain rotation
                    if domain != last_domain:
                        if domain not in domains_processed:
                            domains_processed.append(domain)
                        same_domain_consecutive = 0
                        last_domain = domain
                    else:
                        same_domain_consecutive += 1

                    # Reset failure count on success
                    if domain in domain_failures:
                        domain_failures[domain] = 0

                    # Initialize wire detection state
                    raw_author = content.get("author")
                    cleaned_author = None
                    wire_service_info = None
                    article_status = "extracted"
                    byline_result = None

                    metadata_value = content.get("metadata") or {}
                    if not isinstance(metadata_value, dict):
                        metadata_value = {}

                    # =========================================================
                    # STAGE 1: Wire hints from JSON-LD/structured metadata
                    # (highest priority - check before byline detection)
                    # =========================================================
                    wire_hints = metadata_value.get("wire_hints")
                    if isinstance(wire_hints, dict):
                        hint_services = [
                            svc for svc in wire_hints.get("wire_services", []) if svc
                        ]
                        if hint_services:
                            article_status = "wire"
                            wire_service_info = json.dumps(hint_services)

                            wire_hints["wire_services"] = hint_services

                            detection_details = metadata_value.setdefault(
                                "wire_detection", {}
                            )

                            # Determine detection source
                            detected_by_list = wire_hints.get("detected_by", [])
                            if "gannett_jsonld" in detected_by_list:
                                detection_key = "gannett_jsonld"
                            elif "structured_metadata" in detected_by_list:
                                detection_key = "structured_metadata"
                            else:
                                detection_key = "hearst_source_name"

                            detection_details[detection_key] = {
                                "raw_source_name": wire_hints.get("raw_source_name"),
                                "wire_services": hint_services,
                                "detected_by": detected_by_list,
                                "evidence": wire_hints.get("evidence"),
                                "detected_at": datetime.utcnow().isoformat(),
                            }

                            # Even for wire content, extract any author info so
                            # we don't lose byline data from the extraction
                            extracted_authors: list[str] = []

                            # 1. Try to clean raw_author if available
                            if raw_author:
                                byline_cleaned = byline_cleaner.clean_byline(
                                    raw_author,
                                    return_json=True,
                                    source_name=source,
                                    candidate_link_id=str(url_id),
                                )
                                extracted_authors = byline_cleaned.get("authors", [])

                            # 2. Also check raw_source_name from wire_hints
                            # which may contain author info like "John Smith, Reuters"
                            raw_sources = wire_hints.get("raw_source_name", [])
                            if isinstance(raw_sources, str):
                                raw_sources = [raw_sources]
                            for raw_src in raw_sources:
                                if raw_src and isinstance(raw_src, str):
                                    # Try to extract non-wire author from source
                                    src_cleaned = byline_cleaner.clean_byline(
                                        raw_src,
                                        return_json=True,
                                        source_name=source,
                                        candidate_link_id=str(url_id),
                                    )
                                    for auth in src_cleaned.get("authors", []):
                                        if auth and auth not in extracted_authors:
                                            extracted_authors.append(auth)

                            # Create byline result for wire content with any
                            # extracted authors preserved
                            byline_result = {
                                "authors": extracted_authors,
                                "count": len(extracted_authors),
                                "primary_author": (
                                    extracted_authors[0] if extracted_authors else None
                                ),
                                "has_multiple_authors": len(extracted_authors) > 1,
                                "wire_services": hint_services,
                                "is_wire_content": True,
                                "primary_wire_service": hint_services[0],
                            }

                            logger.info(
                                "Wire detected via %s: wire=%s, authors=%s (skipping content detection)",
                                detection_key,
                                hint_services,
                                extracted_authors,
                            )

                    # =========================================================
                    # STAGE 2: Byline wire detection
                    # (SKIPPED if already detected as wire via metadata)
                    # =========================================================
                    if article_status != "wire" and raw_author:
                        # Get full JSON result with wire service detection
                        byline_cleaned = byline_cleaner.clean_byline(
                            raw_author,
                            return_json=True,
                            source_name=source,
                            candidate_link_id=str(url_id),
                        )

                        # Extract cleaned authors and wire service information
                        cleaned_list = byline_cleaned.get("authors", [])
                        byline_wire_services = byline_cleaned.get("wire_services", [])
                        byline_is_wire = byline_cleaned.get("is_wire_content", False)

                        # Store cleaned authors as human-readable string
                        cleaned_author = _format_cleaned_authors(cleaned_list)

                        # Handle wire service detection from byline
                        if byline_is_wire and byline_wire_services:
                            article_status = "wire"
                            wire_service_info = json.dumps(byline_wire_services)
                            byline_result = byline_cleaned
                            logger.info(
                                "Wire service via byline '%s': authors=%s, wire=%s (skipping content detection)",
                                raw_author,
                                cleaned_list,
                                byline_wire_services,
                            )
                        else:
                            # Not wire - just use byline result
                            byline_result = byline_cleaned
                            logger.info(
                                "Author cleaning: '%s' → '%s'",
                                raw_author,
                                cleaned_list,
                            )

                    if byline_result:
                        metadata_value["byline"] = byline_result

                    # =========================================================
                    # STAGE 3: ContentTypeDetector (URL, author, content patterns)
                    # (only if not already detected as wire)
                    # =========================================================
                    if article_status == "extracted":
                        # Create detector with session to reuse DB connection
                        detector = ContentTypeDetector(session=session)
                        detection_result = detector.detect(
                            url=url,
                            title=content.get("title"),
                            metadata=metadata_value,
                            content=content.get("content"),
                            raw_html=content.get("html"),
                        )
                        if detection_result:
                            article_status = detection_result.status
                            detection_payload = {
                                "status": detection_result.status,
                                "confidence": detection_result.confidence,
                                "confidence_score": (detection_result.confidence_score),
                                "reason": detection_result.reason,
                                "evidence": detection_result.evidence,
                                "version": detection_result.detector_version,
                                "detected_at": datetime.utcnow().isoformat(),
                            }
                            metadata_value["content_type_detection"] = detection_payload

                    # Update metadata if we added detection info
                    if metadata_value:
                        content["metadata"] = metadata_value

                    # Sanity guard: avoid wire status with no evidence
                    if article_status == "wire":
                        has_wire_hints = bool(metadata_value.get("wire_hints"))
                        has_wire_detection = bool(
                            metadata_value.get("wire_detection")
                            or metadata_value.get("content_type_detection")
                        )
                        byline_is_wire = bool(
                            (metadata_value.get("byline") or {}).get("is_wire_content")
                        )
                        has_wire_payload = bool(wire_service_info)

                        if not (
                            has_wire_hints
                            or has_wire_detection
                            or byline_is_wire
                            or has_wire_payload
                        ):
                            logger.warning(
                                "Wire status without evidence; reverting to extracted: %s",
                                url,
                            )
                            article_status = "extracted"
                            wire_service_info = None

                    now = datetime.utcnow()
                    content_text = content.get("content", "")

                    # THE CANONICAL CAPTURE. Decoded once, never emptied.
                    #
                    # Everything below reads progressively less of the page:
                    # the wall/furniture branches blank content_text and
                    # content["content"] so a wall is never STORED as a body,
                    # and the cleaner strips boilerplate out of what is left.
                    # Both are correct for what gets saved and both destroy the
                    # evidence a classifier needs. looks_like_paywall() even
                    # documents this -- "matches on the raw body, NOT the
                    # stripped one: strip_boilerplate removes these very
                    # phrases" -- yet the gate below asked the cleaned text
                    # anyway, so a wall whose phrases had just been stripped
                    # read as an empty body and was filed not_article. Sedalia,
                    # nwaonline and ~298 rows in one run: real headline, real
                    # date, body gone, labelled "never was an article".
                    #
                    # So the split is explicit: CLASSIFICATION (is this a wall,
                    # is this wire) reads the canonical, SUFFICIENCY (is there
                    # a story left after cleaning) reads the cleaned output.
                    # This is never reassigned -- do not blank it to signal a
                    # decision; the storage variables above already do that.
                    canonical_text = _decode_capture(content_text or "")

                    # "Body dropped" is now an explicit decision rather than a
                    # side effect of blanking variables. It has to be: with the
                    # canonical preserved, the cleaned_text fallback further
                    # down (stripped or decoded or content_text) would restore
                    # the very wall/furniture the gate just rejected.
                    body_dropped = False

                    # Validate content length - mark paywall articles
                    # Articles with <150 chars non-boilerplate: status='paywall'
                    # Tracked in DB but excluded from ML/BigQuery:
                    # - entity_extraction.py: skips paywall/wire/error
                    # - analysis.py: EXCLUDED_STATUSES includes paywall
                    # - BigQuery: only exports status='labeled' AND wire_check_status='complete'
                    # Uses database boilerplate patterns to strip noise
                    MIN_CONTENT_LENGTH = 150
                    cleaning_metadata = {}

                    # The capture gate already recognised a subscription wall
                    # (boilerplate.looks_like_paywall). Trust that verdict here
                    # rather than re-deriving it from length: the existing
                    # check below only fires under MIN_CONTENT_LENGTH, and a
                    # wall wrapped in a site's nav menu clears that easily --
                    # greenfieldvedette.com served 1,039 chars of menu plus
                    # "This content is for subscribers only" and would have
                    # been stored as a normal article whose body is furniture.
                    #
                    # Headline, byline and date live OUTSIDE the wall, so they
                    # are kept; only the wall text is discarded as the body.
                    capture_meta = content.get("metadata") or {}
                    gate_says_paywall = (
                        capture_meta.get("capture_rejected_as") == "paywall"
                    )
                    if gate_says_paywall:
                        logger.warning(
                            "Paywall wall detected (%s) - saving metadata only: %s",
                            capture_meta.get("paywall_marker"),
                            url,
                        )
                        # Drop the wall text so furniture is never stored as a
                        # body; the headline/byline/date captured alongside it
                        # are kept by the save below.
                        # Canonical preserved: only the cleaned body is
                        # dropped. See the note on the furniture branch below.

                    if content_text:
                        from urllib.parse import urlparse

                        domain = urlparse(url).netloc
                        # ROT47 must be undone before the cleaner runs, or every
                        # length check below counts ciphertext as article body:
                        # a fully-paywalled page reads as ~4,000 healthy chars
                        # and never trips the paywall branch.
                        decoded_text = _decode_capture(content_text)
                        # Clean content using persistent patterns from database
                        # Note: Some test implementations may not support dry_run parameter
                        try:
                            stripped_content, cleaning_metadata = (
                                content_cleaner.process_single_article(
                                    text=decoded_text,
                                    domain=domain,
                                    dry_run=True,  # Don't modify the original content
                                )
                            )
                        except TypeError:
                            # Fallback for test mocks without dry_run parameter
                            stripped_content, cleaning_metadata = (
                                content_cleaner.process_single_article(
                                    decoded_text, domain
                                )
                            )
                    else:
                        decoded_text = ""
                        stripped_content = ""

                    # SECOND CLEANING PASS, chained onto the first.
                    #
                    # The pattern cleaner above removes what it has LEARNED for
                    # this source (persistent_boilerplate_patterns). That is
                    # per-source and needs a pattern to already exist, so on a
                    # host it has not learned yet it removes nothing: measured
                    # 2026-07-28 over a 3-hour production run, 120 cleaning
                    # sessions ran and recorded ZERO removed segments.
                    #
                    # strip_furniture is the vendor-independent half -- it needs
                    # no prior knowledge of the site. Without this the semantic
                    # detector only ever GATED (decided paywall vs not_article)
                    # and never shaped the body that gets stored, so a capture
                    # whose host had no learned pattern was saved with its
                    # furniture intact.
                    #
                    # CHAINED, never substituted: this runs ON the pattern
                    # cleaner's output, so both passes' removals survive and
                    # neither overwrites the other. Each stage only ever removes
                    # more, and `content` is untouched by both.
                    # excise_furniture_lines, NOT strip_furniture: the latter
                    # is the detection-side function and is too destructive to
                    # edit a stored body with. Measured over the 161 bodies this
                    # pipeline stored on 2026-07-28, it rewrote 149 of them by
                    # collapsing newlines and it deleted a maconhomepress.com
                    # honor roll as a "menu run". The write path removes only
                    # what vocabulary and concepts positively identify, and
                    # leaves every other byte alone.
                    furniture_kinds: frozenset[str] = frozenset()
                    if stripped_content:
                        deboned, furniture_kinds = excise_furniture_lines(
                            stripped_content
                        )
                        if deboned != stripped_content:
                            logger.info(
                                "Furniture pass removed %d chars (%s) that no "
                                "learned pattern covered: %s",
                                len(stripped_content) - len(deboned),
                                ",".join(sorted(furniture_kinds)) or "-",
                                url,
                            )
                            stripped_content = deboned

                    # CLASSIFICATION -- read the canonical, not the cleaned
                    # text. The marker list already covers these walls: the
                    # Sedalia prompt matches "otherwise, click here to view
                    # your options for subscribing", which is in
                    # PAYWALL_MARKERS today. It was never missing detection,
                    # only ever asked of text the cleaner had already stripped
                    # the phrases out of. Note this is additive -- it does not
                    # replace gate_says_paywall or the cleaner's own patterns,
                    # so a wall any one of the three recognises still counts.
                    paywall_marker = looks_like_paywall(canonical_text)
                    has_paywall_patterns = (
                        gate_says_paywall
                        or paywall_marker is not None
                        # The KIND the furniture pass found selects the status.
                        # This is the point of returning a kind at all: a wall
                        # it excised means content exists and is withheld
                        # (retryable with credentials), while a cookie table or
                        # nav bar it excised means the opposite. Without this
                        # the pass would silently empty a walled body and the
                        # gate would call the result not_article -- the exact
                        # mislabel this work exists to stop.
                        or PAYWALL in furniture_kinds
                        or any(
                            pattern in cleaning_metadata.get("patterns_matched", [])
                            for pattern in ["subscription", "paywall"]
                        )
                    )
                    if paywall_marker and not gate_says_paywall:
                        # Record WHICH prompt fired: looks_like_paywall returns
                        # the phrase rather than a bool precisely so the verdict
                        # can be audited and the list tuned from real captures.
                        logger.info(
                            "Paywall marker in canonical capture (%r) that the "
                            "cleaned text no longer carried: %s",
                            paywall_marker,
                            url,
                        )
                    is_insufficient_content = (
                        not stripped_content
                        or len(stripped_content.strip()) < MIN_CONTENT_LENGTH
                    )

                    # Shape gate: a capture can clear the length threshold and
                    # still be pure furniture -- a comment-form country dropdown
                    # (5,308 chars of "X, Republic of ..."), a subscription wall
                    # wrapped in a site's nav menu, a page whose body is only a
                    # PDF embed notice. looks_like_furniture combines the same
                    # measured signals the cleaner already uses (utility-word
                    # rate, capitalisation, boilerplate markers), so it catches
                    # these by SHAPE, not by matching exact phrases -- and it
                    # leaves unusual-but-real prose alone (Spanish articles score
                    # low on the English-only prose density but read as
                    # sentences; public-records columns have real structure).
                    # Verified against the 216-article 2026-07-26 run: flags
                    # 8/8 country dropdowns, 9/9 subscription walls, 2/2 PDF
                    # embeds, 0 of the Spanish captures.
                    is_furniture = bool(stripped_content) and looks_like_furniture(
                        stripped_content
                    )

                    # A wall (short OR long/nav-wrapped) keeps its metadata and
                    # drops the furniture body. Long non-prose without a wall
                    # marker is a mis-extraction or prose-less page -> not_article
                    # (also kept, also body-dropped, also excluded from ML).
                    # WIRE IS TERMINAL. Once wire is affirmatively identified
                    # -- by byline above, or by the content detector, and only
                    # after the evidence guard has had its say -- no later stage
                    # may reclassify it. This gate ran unconditionally and did
                    # exactly that: syndicated stories behind a wall arrived
                    # here with an empty body and were rewritten to not_article,
                    # discarding a wire attribution that had already been
                    # established. Observed on rows carrying
                    # wire=["The Associated Press"] and wire=["Washington Post"]
                    # -- the syndicator was known and thrown away.
                    #
                    # A wire story that is also walled is still a wire story;
                    # its provenance does not depend on whether we got the body.
                    if article_status == "wire":
                        logger.info(
                            "Wire already established (%s); shape gate skipped: %s",
                            wire_service_info,
                            url,
                        )
                    elif (
                        is_insufficient_content or is_furniture
                    ) and has_paywall_patterns:
                        non_boilerplate_len = (
                            len(stripped_content.strip()) if stripped_content else 0
                        )
                        logger.warning(
                            f"Article has paywall indicators - marking as paywall "
                            f"({non_boilerplate_len} chars non-boilerplate, "
                            f"furniture={is_furniture}): {url}"
                        )
                        # Set status='paywall' to save but skip ML
                        article_status = "paywall"
                        # Drop the furniture/wall so it is never stored as a body;
                        # headline/byline/date captured alongside it are kept.
                        # decoded_text is cleared too, or the cleaned_text
                        # fallback below would restore the furniture from it.
                        # Drop the BODY, not the canonical. `content` is the
                        # capture as taken and is never edited after capture --
                        # `text` is the cleaned, consumable field, and emptying
                        # that is what "body dropped" means. Blanking
                        # content["content"] here destroyed the only durable
                        # copy of the wall (raw HTML in GCS ages out at 30
                        # days), which is why these rows show content=0 AND
                        # text=0, and why the paywall could not be recognised
                        # afterwards from the row itself.
                        body_dropped = True
                        stripped_content = ""
                        decoded_text = ""
                    elif is_furniture:
                        logger.warning(
                            f"Article body is furniture, not prose (cap/util shape) "
                            f"- marking as not_article ({len(stripped_content.strip())} "
                            f"chars): {url}"
                        )
                        # Keep the record and its metadata, drop the furniture body.
                        article_status = "not_article"
                        # Drop the BODY, not the canonical. `content` is the
                        # capture as taken and is never edited after capture --
                        # `text` is the cleaned, consumable field, and emptying
                        # that is what "body dropped" means. Blanking
                        # content["content"] here destroyed the only durable
                        # copy of the wall (raw HTML in GCS ages out at 30
                        # days), which is why these rows show content=0 AND
                        # text=0, and why the paywall could not be recognised
                        # afterwards from the row itself.
                        body_dropped = True
                        stripped_content = ""
                        decoded_text = ""
                    elif is_insufficient_content:
                        # Short content but no paywall indicators - skip entirely
                        non_boilerplate_len = (
                            len(stripped_content.strip()) if stripped_content else 0
                        )
                        logger.warning(
                            f"Article has insufficient content without paywall indicators - skipping "
                            f"({non_boilerplate_len} chars non-boilerplate < {MIN_CONTENT_LENGTH}): {url}"
                        )
                        session.execute(
                            text(
                                "UPDATE candidate_links SET status = :status, error_message = :error WHERE id = :id"
                            ),
                            {
                                "id": str(url_id),
                                "status": "extracted",
                                "error": "Insufficient content (no paywall detected)",
                            },
                        )
                        try:
                            _commit_with_retry(session)
                        except Exception as commit_error:
                            logger.error(
                                "Failed to commit insufficient-content update for %s: %s",
                                url,
                                commit_error,
                                exc_info=True,
                            )
                            raise
                        continue  # Skip to next article

                    # Keep BOTH sides of the clean. The cleaner already ran above,
                    # but only to sniff for paywall patterns — its output was
                    # discarded and the raw capture was written to `content` AND
                    # `text`. That is why the two columns were byte-identical for
                    # 96,169 of 96,170 stored articles, why 12.1% of them still
                    # carried boilerplate, and why the smoke test's "content
                    # reduction" metric could only ever read 0%.
                    #
                    # `content` = raw capture, `text` = cleaned body. That is the
                    # pair every consumer already assumes: content_cleaner reads
                    # a.content as its input, entity extraction reads a.text as
                    # the cleaned result.
                    #
                    # Fall back to the raw text if cleaning returned nothing, so a
                    # cleaner failure degrades to today's behaviour rather than
                    # storing an empty body. Paywall rows reach here with a short
                    # stripped_content by design — that IS the finding, and the
                    # raw prose is still preserved in `content`.
                    #
                    # The fallback takes the DECODED text, never the raw capture:
                    # on a ROT47 page a cleaner failure would otherwise store
                    # ciphertext as the article body.
                    # An explicitly dropped body stays dropped: `text` is
                    # empty, `content` keeps the capture. Without this the
                    # fallback would reach content_text and store the wall.
                    if body_dropped:
                        cleaned_text = ""
                    else:
                        cleaned_text = stripped_content or decoded_text or content_text

                    # Hash the cleaned side: text_hash describes `text`, and entity
                    # extraction records it as article_entities.article_text_hash to
                    # mark which version of the text its entities came from.
                    text_hash = calculate_content_hash(cleaned_text)

                    metrics.set_content_type_detection(detection_payload)
                    _attach_driver_metrics(metrics, extractor, domain)
                    # Hand telemetry our own verdict. A filtered body
                    # (paywall/not_article) is emptied above, so no body-based
                    # rule can tell a deliberate drop from a failed capture --
                    # which is why 407 filtered rows looked like errors and 75
                    # stored articles looked like losses.
                    metrics.finalize(content or {}, outcome=article_status)

                    # Diagnostic: optionally dump SQL and parameters before execution
                    try:
                        dump_sql_flag = getattr(args, "dump_sql", False)
                    except Exception:
                        dump_sql_flag = False

                    wire_check_status = _initial_wire_check_status(article_status)

                    # Prefer canonical URL if available (preserves wire path indicators)
                    article_url = _get_canonical_url(url, content.get("metadata", {}))

                    # Archive the page we just parsed so a candidate extractor
                    # can be replayed against identical bytes. Only articles we
                    # actually persist are stored; failures return None.
                    raw_html, raw_html_method = _capture_raw_html(extractor)
                    raw_gcs_path = archive_html(
                        article_url, raw_html, article_id, raw_html_method
                    )

                    if dump_sql_flag:
                        try:
                            logger.info(
                                "[DIAGNOSTIC] About to execute ARTICLE_INSERT_SQL: %s",
                                str(ARTICLE_INSERT_SQL),
                            )
                            # Log a compact params snapshot to avoid huge logs
                            logger.info(
                                "[DIAGNOSTIC] Article params: %s",
                                json.dumps(
                                    {
                                        "id": article_id,
                                        "candidate_link_id": str(url_id),
                                        "url": article_url,
                                        "original_url": (
                                            url if url != article_url else None
                                        ),
                                        "title": content.get("title"),
                                    }
                                ),
                            )
                        except Exception:
                            logger.exception("Failed to log diagnostic SQL/params")

                    insert_result = safe_session_execute(
                        session,
                        ARTICLE_INSERT_SQL,
                        {
                            "id": article_id,
                            "candidate_link_id": str(url_id),
                            "url": article_url,
                            "title": content.get("title"),
                            "author": cleaned_author,
                            "publish_date": content.get("publish_date"),
                            "content": content_text,
                            "text": cleaned_text,  # cleaned; raw stays in content
                            "status": article_status,
                            "metadata": json.dumps(content.get("metadata", {})),
                            "wire": wire_service_info,
                            "wire_check_status": wire_check_status,
                            "wire_check_attempted_at": None,
                            "wire_check_error": None,
                            "wire_check_metadata": None,
                            "extracted_at": now.isoformat(),
                            "created_at": now.isoformat(),
                            "text_hash": text_hash,
                            "raw_gcs_path": raw_gcs_path,
                        },
                    )
                    # Did the INSERT actually write a row? ARTICLE_INSERT_SQL
                    # ends in ON CONFLICT DO NOTHING against uq_articles_url, so
                    # a URL already stored under a different candidate_link is
                    # skipped silently -- and until safe_session_execute stopped
                    # swallowing failures, so was any other error. Either way the
                    # next statement marked the link 'extracted' and committed,
                    # so the status asserted an article that did not exist: 176
                    # such links on one publisher, 142 of them with no article
                    # anywhere and the captured body gone.
                    #
                    # Claim 'extracted' only when a row was written. A conflict
                    # is not an error -- the article exists, under another link --
                    # but this link did not produce one and must not say it did.
                    inserted = getattr(insert_result, "rowcount", 1)
                    if inserted == 0:
                        logger.error(
                            "Article INSERT wrote no row for %s (id=%s); most "
                            "likely a uq_articles_url conflict with an existing "
                            "article. Leaving candidate_link status unchanged "
                            "rather than claiming 'extracted'.",
                            article_url,
                            article_id,
                        )
                    else:
                        safe_session_execute(
                            session,
                            CANDIDATE_STATUS_UPDATE_SQL,
                            {"status": article_status, "id": str(url_id)},
                        )

                    # Explicit commit with logging to catch silent failures
                    try:
                        session.commit()
                        logger.debug(
                            "Successfully committed article %s (%s) to database",
                            article_id,
                            article_url[:80],
                        )
                    except Exception as commit_error:
                        logger.error(
                            "Database commit failed for article %s: %s",
                            article_id,
                            commit_error,
                            exc_info=True,
                        )
                        raise
                    # Post-commit verification (diagnostic): optionally verify row exists
                    try:
                        verify_flag = getattr(args, "verify_insert", False)
                    except Exception:
                        verify_flag = False

                    if verify_flag:
                        try:
                            # Prefer to verify by id; fallback to url if id-based check fails
                            verify_row = safe_session_execute(
                                session,
                                text("SELECT id, url FROM articles WHERE id = :id"),
                                {"id": article_id},
                            ).fetchone()
                            if not verify_row:
                                # Try verify by URL as a second check
                                verify_row = safe_session_execute(
                                    session,
                                    text(
                                        "SELECT id, url FROM articles WHERE url = :url"
                                    ),
                                    {"url": article_url},
                                ).fetchone()

                            if verify_row:
                                logger.info(
                                    "[DIAGNOSTIC] Verified inserted article in DB: %s",
                                    dict(verify_row),
                                )
                            else:
                                logger.error(
                                    "[DIAGNOSTIC] Post-commit verification FAILED for article %s (url=%s)",
                                    article_id,
                                    article_url,
                                )
                                # As extra diagnostic, count matching rows by url
                                try:
                                    cnt = safe_session_execute(
                                        session,
                                        text(
                                            "SELECT COUNT(*) FROM articles WHERE url = :url"
                                        ),
                                        {"url": article_url},
                                    ).scalar()
                                except Exception:
                                    cnt = None
                                logger.error(
                                    "[DIAGNOSTIC] Matching rows by url: %s", cnt
                                )
                        except Exception:
                            logger.exception(
                                "[DIAGNOSTIC] Exception while verifying inserted article"
                            )

                    telemetry.record_extraction(metrics)
                    domains_for_cleaning[domain].append(article_id)
                    processed += 1
                    logger.info(
                        "✅ Article saved and counted: %s (total processed: %d)",
                        article_id[:8],
                        processed,
                    )
                else:
                    # Track failure for domain awareness
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1

                    # If domain has failed too many times,
                    # skip it for rest of batch
                    if domain_failures[domain] >= max_failures_per_domain:
                        logger.warning(
                            "Domain %s failed %s times; skipping batch",
                            domain,
                            domain_failures[domain],
                        )
                        skipped_domains.add(domain)

                    # For rate limit errors or bot protection (403), also add to
                    # skipped domains immediately
                    error_msg = content.get("error", "") if content else ""
                    http_status = content.get("http_status") if content else None
                    is_rate_limit = "Rate limited" in error_msg or "429" in error_msg
                    is_bot_protection = http_status == 403

                    if is_rate_limit or is_bot_protection:
                        logger.warning(
                            "Rate limit/bot protection (%s) for %s; "
                            "skipping remaining URLs in batch",
                            http_status or "429",
                            domain,
                        )
                        skipped_domains.add(domain)

                    metrics.error_message = "No title extracted"
                    metrics.error_type = "extraction_failure"
                    metrics.set_content_type_detection(detection_payload)
                    _attach_driver_metrics(metrics, extractor, domain)
                    metrics.finalize(content or {})
                    telemetry.record_extraction(metrics)

            except NotFoundError as e:
                # 404/410 - permanently mark as not found and continue to next URL
                logger.info("URL not found (404/410): %s", url)
                try:
                    safe_session_execute(
                        session,
                        CANDIDATE_STATUS_UPDATE_SQL,
                        {"status": "404", "id": str(url_id)},
                    )
                    session.commit()
                except Exception:
                    logger.exception("Failed to mark URL as 404: %s", url)
                    session.rollback()

                metrics.error_message = str(e)
                metrics.error_type = "not_found"
                _attach_driver_metrics(metrics, extractor, domain)
                metrics.finalize({})
                telemetry.record_extraction(metrics)
                # Skip counting 404s against aggregate domain failures
                continue

            except ProxyChallengeError as e:
                # Proxy challenge/block - mark for retry with cooldown
                logger.warning("Proxy challenge detected for %s: %s", url, e)
                try:
                    # Don't mark as failed - keep status as 'article' so it gets retried later
                    # This allows the article to be picked up again after cooldown period
                    logger.info(
                        "Keeping article %s in 'article' status for retry after cooldown",
                        url,
                    )
                    # Optionally: could add last_attempt_at timestamp to track cooldown
                    # For now, rely on natural batch rotation to provide cooldown
                except Exception:
                    logger.exception("Failed to handle proxy challenge for %s", url)
                    session.rollback()

                # Track as domain failure to skip remaining URLs from this domain
                domain_failures[domain] = domain_failures.get(domain, 0) + 1
                logger.warning(
                    "Domain %s proxy challenge (#%d); skipping remaining URLs in batch",
                    domain,
                    domain_failures[domain],
                )
                skipped_domains.add(domain)

                metrics.error_message = str(e)
                metrics.error_type = "proxy_challenge"
                _attach_driver_metrics(metrics, extractor, domain)
                metrics.finalize({})
                telemetry.record_extraction(metrics)
                continue

            except Exception as e:
                # Check for rate limit or bot protection in exception
                error_str = str(e)
                is_rate_limit = "Rate limited" in error_str or "429" in error_str
                is_bot_protection = "403" in error_str or "Forbidden" in error_str

                if is_rate_limit or is_bot_protection:
                    # Check if this is a known paywall domain
                    is_paywall_403 = is_bot_protection and any(
                        pd in domain for pd in PAYWALL_DOMAINS
                    )

                    if is_paywall_403:
                        logger.warning(
                            "Paywall (403) detected for %s; marking as 403 and continuing",
                            url,
                        )
                        try:
                            safe_session_execute(
                                session,
                                CANDIDATE_STATUS_UPDATE_SQL,
                                {"status": "403", "id": str(url_id)},
                            )
                            session.commit()
                        except Exception:
                            logger.exception("Failed to mark URL as 403")
                            session.rollback()

                        # Do NOT add to skipped_domains, do NOT pause domain
                        # Just continue to next article (which will likely also be 403'd and marked)
                    else:
                        logger.warning(
                            "Rate limit/bot protection exception for %s, "
                            "skipping remaining URLs",
                            domain,
                        )
                        skipped_domains.add(domain)
                        domain_failures[domain] = max_failures_per_domain
                        # Cap at max failures once rate limited/blocked
                        # If this looks like bot protection (HTTP 403), attempt to
                        # proactively pause candidate links for this host so we
                        # don't keep retrying and triggering more blocks.
                        try:
                            host_val = getattr(metrics, "host", domain)
                            if host_val:
                                reason = "Auto-paused: multiple HTTP 403 responses"
                                host_like = f"%{host_val}%"
                                safe_session_execute(
                                    session,
                                    PAUSE_CANDIDATE_LINKS_SQL,
                                    {
                                        "status": "paused",
                                        "error": reason,
                                        "host_like": host_like,
                                        "host": host_val,
                                    },
                                )
                                session.commit()
                                logger.warning(
                                    "Auto-paused host %s after exception", host_val
                                )
                        except Exception:
                            # Don't raise from the pause attempt; just log and continue
                            logger.exception(
                                "Failed to auto-pause host during exception handling"
                            )
                else:
                    # Track other failures for domain awareness
                    domain_failures[domain] = domain_failures.get(domain, 0) + 1
                    if domain_failures[domain] >= max_failures_per_domain:
                        logger.warning(
                            "Domain %s failed %s times; skipping batch",
                            domain,
                            domain_failures[domain],
                        )
                        skipped_domains.add(domain)

                # Log the full exception traceback so it's not swallowed
                logger.error("Extraction exception for %s: %s", url, e, exc_info=True)

                metrics.error_message = str(e)
                metrics.error_type = "exception"
                _attach_driver_metrics(metrics, extractor, domain)
                metrics.finalize({})
                telemetry.record_extraction(metrics)
                session.rollback()

                # Check for 404/410 responses and mark them as dead
                status_code = getattr(metrics, "http_status_code", None)
                host = getattr(metrics, "host", None)

                if status_code in (404, 410):
                    # Permanently mark as 404 - page doesn't exist
                    try:
                        safe_session_execute(
                            session,
                            CANDIDATE_STATUS_UPDATE_SQL,
                            {"status": "404", "id": str(url_id)},
                        )
                        session.commit()
                        logger.info(
                            "Marked URL as 404 (not found): %s",
                            url,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark URL as 404: %s",
                            url,
                        )
                        session.rollback()

                # Check if this was a 403 response and track it
                elif status_code == 403 and host:
                    # Track this host's 403 errors
                    seen = host_403_tracker.setdefault(host, set())
                    seen.add(str(url_id))

                    # If we've seen multiple 403s from this host in this run,
                    # mark all candidate links from this host as paused
                    if len(seen) >= 2:
                        reason = "Auto-paused: multiple HTTP 403 responses"
                        host_like = f"%{host}%"
                        try:
                            safe_session_execute(
                                session,
                                PAUSE_CANDIDATE_LINKS_SQL,
                                {
                                    "status": "paused",
                                    "error": reason,
                                    "host_like": host_like,
                                    "host": host,
                                },
                            )
                            session.commit()
                            logger.warning(
                                "Auto-paused host %s after repeated 403s",
                                host,
                            )
                        except Exception:
                            logger.exception(
                                "Failed to pause candidate links for %s",
                                host,
                            )
                            session.rollback()

        # Log domain skipping summary
        if skipped_domains:
            skipped_list = ", ".join(sorted(skipped_domains))
            logger.info(
                "Batch %s skipped domains due to failures: %s",
                batch_num,
                skipped_list,
            )

            # Report failures to work queue service if enabled
            if USE_WORK_QUEUE:
                worker_id = _get_worker_id()
                for domain in skipped_domains:
                    _report_domain_failure(worker_id, domain)

        if domain_failures:
            failure_summary = {
                key: value for key, value in domain_failures.items() if value > 0
            }
            if failure_summary:
                logger.info(
                    "Batch %s domain failure counts: %s",
                    batch_num,
                    failure_summary,
                )

        return {
            "processed": processed,
            "skipped_domains": len(skipped_domains),
            "domains_processed": domains_processed,
            "same_domain_consecutive": same_domain_consecutive,
            "domain_article_count": domain_article_count,
        }

    finally:
        session.close()


def _run_post_extraction_cleaning(domains_to_articles, db=None):
    """Trigger content cleaning for recently extracted articles."""
    provided_db = db is not None
    if not provided_db:
        db = DatabaseManager()
    cleaner_cls = BalancedBoundaryContentCleaner
    cleaner_kwargs: dict[str, Any] = {}

    try:
        cleaner_signature = inspect.signature(cleaner_cls)
    except (TypeError, ValueError):
        cleaner_signature = None

    supports_kwargs = False
    if cleaner_signature is not None:
        params = cleaner_signature.parameters
        supports_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
        )

        if "enable_telemetry" in params or supports_kwargs:
            cleaner_kwargs["enable_telemetry"] = True
        if db is not None and ("db" in params or supports_kwargs):
            cleaner_kwargs["db"] = db
    else:
        cleaner_kwargs["enable_telemetry"] = True
        if db is not None:
            cleaner_kwargs["db"] = db

    cleaner = cleaner_cls(**cleaner_kwargs)
    # Handle both DatabaseManager objects and raw Sessions
    session = db.session if hasattr(db, "session") else db
    articles_for_entities: set[str] = set()

    try:
        for domain, article_ids in domains_to_articles.items():
            if not article_ids:
                continue

            try:
                # Pass session to prevent opening new connections and transaction conflicts
                cleaner.analyze_domain(domain, session=session)
            except Exception as e:
                # Domain analysis is optional optimization - skip if tables don't exist
                error_str = str(e)
                if "no such table: articles" in error_str:
                    logger.debug(
                        "Skipping domain analysis for %s (table doesn't exist)", domain
                    )
                else:
                    logger.warning(
                        "Domain analysis failed for %s: %s", domain, error_str
                    )
                # Rollback transaction if it's in an aborted state (PostgreSQL error 25P02)
                if "25P02" in error_str or "transaction is aborted" in error_str:
                    try:
                        session.rollback()
                        logger.debug(
                            "Rolled back aborted transaction for domain %s", domain
                        )
                    except Exception as rollback_error:
                        logger.warning(
                            "Failed to rollback transaction: %s", rollback_error
                        )
                # Continue with cleaning even if analysis fails

            for article_id in article_ids:
                try:
                    row = safe_session_execute(
                        session,
                        text(
                            "SELECT title, content, status FROM articles WHERE id = :id"
                        ),
                        {"id": article_id},
                    ).fetchone()

                    if not row:
                        continue

                    title = row[0] or ""
                    original_content = row[1] or ""
                    current_status = row[2] or "extracted"

                    # Check for proxy/bot challenge in title or content
                    proxy_patterns = [
                        "Access to this page has been denied",
                        "Attention Required",
                        "Just a moment",
                        "Please verify you are a human",
                        "Checking your browser",
                        "Access Denied",
                    ]

                    is_proxy_challenge = any(
                        pattern in title or pattern in original_content[:500]
                        for pattern in proxy_patterns
                    )

                    if is_proxy_challenge:
                        logger.warning(
                            "🚫 Proxy challenge during cleaning: %s (title: %s)",
                            article_id[:8],
                            title[:100],
                        )
                        # Mark as error status to exclude from BigQuery
                        safe_session_execute(
                            session,
                            text("UPDATE articles SET status = 'error' WHERE id = :id"),
                            {"id": article_id},
                        )
                        _commit_with_retry(session)
                        continue

                    if not original_content.strip():
                        continue

                    # Re-cleaning reads `content` straight from the database, so
                    # it inherits whatever was stored — including the ciphertext
                    # written by every extraction that ran before this fix. Decode
                    # here too, or re-running the cleaner over the backlog would
                    # faithfully re-clean scrambled text.
                    decoded_content = _decode_capture(original_content)

                    cleaned_content, metadata = cleaner.process_single_article(
                        text=decoded_content,
                        domain=domain,
                        article_id=article_id,
                    )

                    wire_detected = metadata.get("wire_detected")
                    wire_suppressed = bool(
                        metadata.get("wire_suppressed_due_to_local_byline")
                    )
                    if wire_suppressed:
                        wire_detected = None

                    locality_assessment = metadata.get("locality_assessment") or {}
                    is_local_wire = bool(
                        wire_detected
                        and locality_assessment
                        and locality_assessment.get("is_local")
                    )

                    new_status = current_status

                    if wire_suppressed:
                        if current_status in {"wire", "local", "extracted"}:
                            new_status = "cleaned"
                    elif is_local_wire:
                        if current_status in {"wire", "cleaned", "extracted"}:
                            new_status = "local"
                    elif wire_detected:
                        if current_status == "extracted":
                            new_status = "wire"
                    elif current_status == "extracted":
                        new_status = "cleaned"

                    status_changed = new_status != current_status

                    if status_changed and current_status == "extracted":
                        if (
                            ENABLE_MEDIACLOUD_WIRE_CHECK
                            and new_status in WIRE_CHECK_QUEUE_STATUSES
                        ):
                            safe_session_execute(
                                session,
                                ARTICLE_MARK_WIRE_PENDING_SQL,
                                {"id": article_id},
                            )
                        else:
                            safe_session_execute(
                                session,
                                ARTICLE_MARK_WIRE_COMPLETE_SQL,
                                {"id": article_id},
                            )

                    article_updated = False

                    if cleaned_content != original_content:
                        new_hash = (
                            calculate_content_hash(cleaned_content)
                            if cleaned_content
                            else None
                        )
                        excerpt = cleaned_content[:500] if cleaned_content else None

                        safe_session_execute(
                            session,
                            ARTICLE_UPDATE_SQL,
                            {
                                # Re-cleaning writes only the cleaned side. The
                                # raw capture stays as it was, so this can be
                                # re-run against improved rules and the result
                                # compared with what it replaced.
                                "text": cleaned_content,
                                "text_hash": new_hash,
                                "excerpt": excerpt,
                                "status": new_status,
                                "id": article_id,
                            },
                        )

                        logger.info(
                            "Cleaning removed %s chars for article %s (%s)",
                            metadata.get("chars_removed"),
                            article_id,
                            domain,
                        )

                        if status_changed:
                            logger.info(
                                "Updated article %s (%s) status: %s -> %s",
                                article_id,
                                domain,
                                current_status,
                                new_status,
                            )

                        article_updated = True
                    elif status_changed:
                        safe_session_execute(
                            session,
                            ARTICLE_STATUS_UPDATE_SQL,
                            {"status": new_status, "id": article_id},
                        )
                        logger.info(
                            "Updated article %s (%s) status: %s -> %s",
                            article_id,
                            domain,
                            current_status,
                            new_status,
                        )
                        article_updated = True

                    if article_updated:
                        _commit_with_retry(session)

                    status_for_entities = (new_status or "").lower()
                    disallowed_statuses = {"wire", "opinion", "obituary"}
                    if status_for_entities not in disallowed_statuses:
                        # Always queue non-wire articles for entity
                        # extraction so locality comparison data stays fresh
                        # even when content hashes remain unchanged.
                        articles_for_entities.add(article_id)
                except Exception:
                    session.rollback()
                    logger.exception(
                        "Failed to clean article %s for domain %s",
                        article_id,
                        domain,
                    )

    except Exception:
        session.rollback()
        logger.exception("Failed to complete post-extraction content cleaning")
    finally:
        session.close()

    if articles_for_entities:
        if provided_db:
            _run_article_entity_extraction(articles_for_entities, db=db)
        else:
            _run_article_entity_extraction(articles_for_entities)


def _run_article_entity_extraction(article_ids: Iterable[str], db=None) -> None:
    """Extract entities from articles (requires rapidfuzz in processor image)."""
    # Lazy import entity extraction functions
    from src.pipeline.entity_extraction import (
        attach_gazetteer_matches,
        get_gazetteer_rows,
    )

    ids = {article_id for article_id in article_ids if article_id}
    if not ids:
        return

    extractor = _get_entity_extractor()
    logger.info("Running entity extraction for %d articles", len(ids))

    if db is None:
        db = DatabaseManager()
    session = db.session

    try:
        articles = (
            session.query(Article)
            .join(CandidateLink, Article.candidate_link_id == CandidateLink.id)
            .filter(Article.id.in_(ids))
            .all()
        )

        skip_statuses = {"wire", "opinion", "obituary"}

        for article in articles:
            status_value = (article.status or "").lower()
            if status_value in skip_statuses:
                continue

            candidate = article.candidate_link
            if candidate:
                source_id = candidate.source_id
                dataset_id = candidate.dataset_id
            else:
                source_id = None
                dataset_id = None

            raw_text = article.text or article.content
            text_value = raw_text if isinstance(raw_text, str) else None
            gazetteer_rows = get_gazetteer_rows(
                session,
                source_id,
                dataset_id,
            )
            entities = extractor.extract(
                text_value,
                gazetteer_rows=gazetteer_rows,
            )
            entities = attach_gazetteer_matches(
                session,
                source_id,
                dataset_id,
                entities,
                gazetteer_rows=gazetteer_rows,
            )
            save_article_entities(
                session,
                str(getattr(article, "id", "")),
                entities,
                extractor.extractor_version,
                getattr(article, "text_hash", None),
            )
    except Exception:
        session.rollback()
        logger.exception("Entity extraction pipeline failed")
    finally:
        session.close()
