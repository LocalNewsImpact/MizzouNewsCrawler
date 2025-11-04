"""Database-driven URL discovery using newspaper4k and storysniffer.

This module integrates with the existing pipeline by:
1. Reading publisher URLs from the sources table
2. Using newspaper4k for RSS feed discovery and parsing
3. Using storysniffer for intelligent article URL detection
4. Storing discovered candidate URLs in the candidate_links table

Designed for PostgreSQL.
"""

import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser  # type: ignore[import]
import pandas as pd
import requests
import urllib3
from newspaper import Config, build  # type: ignore[import]
from sqlalchemy import text

# Suppress InsecureRequestWarning for proxies without SSL certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .scheduling import parse_frequency_to_days

# Using multiprocessing for build timeouts; no concurrent.futures needed here

try:
    import cloudscraper  # type: ignore[import]
except ImportError:
    cloudscraper = None
try:
    from storysniffer import StorySniffer  # type: ignore[import]
except ImportError:
    StorySniffer = None

# Optional flexible date parser (dateutil). Not required at import time.
try:
    from dateutil.parser import parse as _parse_date
except Exception:
    _parse_date = None  # type: ignore[assignment]

from src.utils.discovery_outcomes import DiscoveryResult
from src.utils.telemetry import (
    DiscoveryMethod,
    DiscoveryMethodStatus,
    OperationMetrics,
    OperationType,
    create_telemetry_system,
)
from src.utils.url_utils import normalize_url

from ..models.database import DatabaseManager, safe_execute, safe_session_execute
from .origin_proxy import enable_origin_proxy
from .proxy_config import get_proxy_manager

logger = logging.getLogger(__name__)


def _newspaper_build_worker(
    target_url: str,
    out_path: str,
    fetch_images_flag: bool,
    proxy: str | None = None,
):
    """Worker function executed in a separate process to perform
    `newspaper.build` and write discovered article URLs to `out_path`.

    Implemented at module-level so it's picklable on platforms using the
    'spawn' start method (macOS).
    """
    try:
        # Set proxy environment variables if provided
        if proxy:
            os.environ["HTTP_PROXY"] = proxy
            os.environ["HTTPS_PROXY"] = proxy
            os.environ["http_proxy"] = proxy
            os.environ["https_proxy"] = proxy

        # Construct a minimal Config instance inside child process
        cfg = Config()
        try:
            cfg.fetch_images = bool(fetch_images_flag)
        except Exception:
            pass

        try:
            p = build(target_url, config=cfg)
            urls = [a.url for a in getattr(p, "articles", [])]
        except Exception:
            urls = []

        # Write URLs back to disk via pickle; best-effort
        try:
            import pickle as _pickle

            with open(out_path, "wb") as fh:
                _pickle.dump(urls, fh)
        except Exception:
            pass
    except Exception:
        # Swallow any unexpected errors in the worker
        return


# How many consecutive non-network failures (e.g. 404/parse) are required
# before we mark a source as permanently missing an RSS feed.
RSS_MISSING_THRESHOLD = 3


class NewsDiscovery:
    """Advanced news URL discovery using newspaper4k and storysniffer."""

    def __init__(
        self,
        database_url: str | None = None,
        user_agent: str | None = None,
        timeout: int = 30,
        delay: float = 2.0,
        max_articles_per_source: int = 50,
        days_back: int = 7,
    ):
        """Initialize the discovery system.

        Args:
            database_url: Database connection string. When omitted, fall back
                to the configured ``DATABASE_URL``. PostgreSQL is required.
            user_agent: User agent string for requests
            timeout: Request timeout in seconds
            delay: Delay between requests in seconds
            max_articles_per_source: Maximum candidate URLs per source
            days_back: How many days back to look for articles
        """
        resolved_database_url = self._resolve_database_url(database_url)
        self.database_url = resolved_database_url
        self.user_agent = (
            user_agent or "Mozilla/5.0 (compatible; MizzouNewsCrawler/2.0)"
        )
        self.timeout = timeout
        self.delay = delay
        self.max_articles_per_source = max_articles_per_source
        self.days_back = days_back

        # Calculate date cutoff for recent articles
        self.cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        # Configure newspaper4k
        self.newspaper_config = Config()
        self.newspaper_config.browser_user_agent = self.user_agent
        self.newspaper_config.request_timeout = timeout
        self.newspaper_config.number_threads = 1  # Be respectful

        # Initialize cloudscraper session for better Cloudflare handling
        if cloudscraper is not None:
            self.session = cloudscraper.create_scraper()
            self.session.headers.update({"User-Agent": self.user_agent})
            logger.info("Cloudscraper initialized for Cloudflare protection")
        else:
            self.session = requests.Session()
            self.session.headers.update({"User-Agent": self.user_agent})
            logger.info("Using standard requests session")

        # Configure proxy behavior (origin adapter or standard proxies)
        self._configure_proxy_routing()

        # Initialize storysniffer client (if available)
        self.storysniffer = None
        if StorySniffer is not None:
            try:
                self.storysniffer = StorySniffer()
                logger.info("StorySniffer initialized successfully")
            except Exception as e:
                logger.warning(f"Could not initialize StorySniffer: {e}")
                logger.info("Continuing with newspaper4k and RSS only")
        else:
            logger.info("StorySniffer not available, using newspaper4k/RSS")

        # Initialize telemetry tracker
        telemetry_database_url = resolved_database_url if database_url else None
        self.telemetry = create_telemetry_system(
            database_url=telemetry_database_url,
        )

        logger.info(f"NewsDiscovery initialized with {days_back}-day window")
        logger.info(
            "Articles published before "
            f"{self.cutoff_date.strftime('%Y-%m-%d')} will be filtered out"
        )
        self._known_hosts_cache: set[str] | None = None

    @staticmethod
    def _resolve_database_url(candidate: str | None) -> str | None:
        if candidate:
            return candidate

        env_db = os.getenv("DATABASE_URL")
        running_pytest = bool(os.getenv("PYTEST_CURRENT_TEST"))
        keep_env = os.getenv("PYTEST_KEEP_DB_ENV", "").lower() == "true"

        if env_db and not env_db.startswith("sqlite:///:memory"):
            return env_db

        configured_url: str | None = None
        try:
            from src.config import DATABASE_URL as configured_database_url

            configured_url = configured_database_url
        except Exception:
            configured_url = None

        if running_pytest and not keep_env:
            forced_test_url = os.getenv("PYTEST_DATABASE_URL")
            if forced_test_url:
                return forced_test_url

            if configured_url and configured_url.startswith("sqlite"):
                return configured_url

            return None

        if configured_url:
            return configured_url

        return None

    def _configure_proxy_routing(self) -> None:
        """Configure proxy adapter and proxy pool for the discovery session."""

        # Legacy environment-driven proxy pool support
        proxy_pool_env = (os.getenv("PROXY_POOL", "") or "").strip()
        env_proxy_pool = (
            [p.strip() for p in proxy_pool_env.split(",") if p.strip()]
            if proxy_pool_env
            else []
        )

        self.proxy_pool = list(env_proxy_pool)

        # Initialize proxy manager for modern provider handling
        self.proxy_manager = get_proxy_manager()
        active_provider = self.proxy_manager.active_provider
        logger.info(
            "🔀 Proxy manager initialized with provider: %s",
            active_provider.value,
        )

        use_origin_proxy = os.getenv("USE_ORIGIN_PROXY", "").lower() in (
            "1",
            "true",
            "yes",
        )

        if active_provider.value == "origin" or use_origin_proxy:
            try:
                enable_origin_proxy(self.session)
                proxy_base = (
                    self.proxy_manager.get_origin_proxy_url()
                    or os.getenv("ORIGIN_PROXY_URL")
                    or os.getenv("PROXY_URL")
                    or "default"
                )
                logger.info(
                    "🔐 Discovery using origin proxy adapter (%s)",
                    proxy_base,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to install origin proxy adapter for discovery: %s",
                    exc,
                )
            return

        proxies = self.proxy_manager.get_requests_proxies()
        if proxies:
            self.session.proxies.update(proxies)
            proxy_values = [p for p in proxies.values() if p]
            if proxy_values:
                merged_pool = env_proxy_pool + proxy_values
                deduped_pool: list[str] = []
                seen: set[str] = set()
                for value in merged_pool:
                    if value and value not in seen:
                        deduped_pool.append(value)
                        seen.add(value)
                self.proxy_pool = deduped_pool
            logger.info(
                "🔐 Discovery using %s proxy provider (%s)",
                active_provider.value,
                ", ".join(sorted(proxies.keys())),
            )
            return

        if self.proxy_pool:
            proxy = random.choice(self.proxy_pool)
            self.session.proxies.update(
                {
                    "http": proxy,
                    "https": proxy,
                }
            )
            logger.info(
                "🔐 Discovery using legacy proxy pool with %d entries (selected %s)",
                len(self.proxy_pool),
                proxy,
            )
        else:
            logger.info(
                "🔐 Proxy provider %s did not supply proxies; using direct connections",
                active_provider.value,
            )

    def _create_db_manager(self) -> DatabaseManager:
        """Factory method for database manager instances."""

        return DatabaseManager(self.database_url)

    @staticmethod
    def _normalize_host(host: str | None) -> str | None:
        """Normalize hostnames for comparison."""

        if not host:
            return None

        value = host.strip()
        if not value:
            return None

        if "//" in value and not value.startswith("//"):
            parsed = urlparse(value)
            value = parsed.netloc or value

        value = value.split("@").pop()  # Drop credentials if provided
        value = value.split(":")[0]  # Remove port
        value = value.lower()

        if value.startswith("www."):
            value = value[4:]

        return value or None

    def _iter_host_candidates(self, value: Any) -> list[str]:
        hosts: list[str] = []
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part]
            hosts.extend(parts)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    hosts.append(item.strip())
        return hosts

    def _collect_allowed_hosts(
        self,
        source_row: pd.Series,
        source_meta: dict | None,
    ) -> set[str]:
        hosts: set[str] = set()

        primary_candidates = [
            source_row.get("host"),
            source_row.get("host_norm"),
        ]

        source_url = str(source_row.get("url", ""))
        if source_url:
            parsed = urlparse(source_url)
            if parsed.netloc:
                primary_candidates.append(parsed.netloc)

        for candidate in primary_candidates:
            normalized = self._normalize_host(candidate)
            if normalized:
                hosts.add(normalized)

        if isinstance(source_meta, dict):
            meta_keys = [
                "alternate_hosts",
                "alternate_domains",
                "allowed_hosts",
                "allowed_domains",
                "domains",
                "hosts",
                "host_aliases",
            ]
            for key in meta_keys:
                value = source_meta.get(key)
                for candidate in self._iter_host_candidates(value):
                    normalized = self._normalize_host(candidate)
                    if normalized:
                        hosts.add(normalized)

        return hosts

    @classmethod
    def _should_skip_rss_from_meta(
        cls,
        source_meta: dict | None,
    ) -> tuple[bool, str | None, int | None]:
        """Determine whether RSS probing should be skipped.

        Returns a tuple ``(skip, reason, failure_count)`` where ``skip`` is a
        boolean indicating if homepage RSS probing should be avoided,``reason``
        is a short string describing why, and ``failure_count`` is the current
        consecutive failure counter, if available.
        """

        if not isinstance(source_meta, dict):
            return False, None, None

        # rss_missing may be either a timestamp or a boolean flag.
        rss_missing = source_meta.get("rss_missing")
        rss_failed_at: str | None
        if isinstance(rss_missing, str):
            rss_failed_at = rss_missing
        elif rss_missing:
            rss_failed_at = datetime.utcnow().isoformat()
        else:
            rss_failed_at = None

        consecutive_failures = source_meta.get("rss_consecutive_failures")
        failure_count: int | None = None
        if consecutive_failures is not None:
            try:
                failure_count = int(consecutive_failures)
            except Exception:
                failure_count = None

        skip = bool(rss_failed_at)
        reason = None
        if skip:
            reason = "rss_missing"

        return skip, reason, failure_count

    @staticmethod
    def _extract_homepage_feed_urls(
        html: str,
        base_url: str,
    ) -> list[str]:
        """Extract RSS/Atom feed URLs from a homepage."""

        if not html:
            return []

        import re

        rss_type = r"(?:application/rss\+xml|application/atom\+xml|text/xml)"
        pattern = (
            r'<link[^>]+type=["\']' + rss_type + r'["\'][^>]*href=["\']([^"\']+)["\']'
        )

        matches = re.findall(pattern, html, flags=re.I)
        if not matches:
            return []

        feeds = [urljoin(base_url, m) for m in matches]
        seen: set[str] = set()
        deduped: list[str] = []
        for feed in feeds:
            if feed in seen:
                continue
            seen.add(feed)
            deduped.append(feed)
        return deduped

    @staticmethod
    def _extract_homepage_article_candidates(
        html: str,
        base_url: str,
        *,
        rss_missing: bool = False,
        max_candidates: int = 25,
    ) -> list[str]:
        if not html:
            return []

        import re

        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)
        if not hrefs:
            return []

        parsed_base = urlparse(base_url)
        candidates: list[str] = []
        seen: set[str] = set()

        for href in hrefs:
            href = href.strip()
            if not href:
                continue
            prefix = href.split(":", 1)[0].lower()
            if prefix in {"mailto", "tel", "javascript"}:
                continue

            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed_base.netloc and parsed.netloc != parsed_base.netloc:
                continue

            path = parsed.path.lower()
            if rss_missing and ("/feed" in path or "/rss" in path):
                continue

            if not any(
                key in path
                for key in (
                    "/news",
                    "/article",
                    "/stories",
                    "/story",
                    "/post",
                    "/202",
                    "/20",
                )
            ):
                continue

            if absolute in seen:
                continue

            seen.add(absolute)
            candidates.append(absolute)

            if len(candidates) >= max_candidates:
                break

        return candidates

    @staticmethod
    def _normalize_candidate_url(url: str) -> str:
        try:
            return normalize_url(url)
        except Exception:
            return url

    def _update_source_meta(
        self,
        source_id: str | None,
        updates: dict[str, Any],
    ):
        """Merge `updates` into the `sources.metadata` JSON for `source_id`.

        This is a best-effort helper that reads the current metadata, merges
        the provided dict, and writes it back as JSON. Failures are logged
        but do not raise to avoid interrupting discovery.
        """
        if not source_id:
            return
        try:
            dbm = DatabaseManager(self.database_url)
            with dbm.engine.begin() as conn:
                res = safe_execute(
                    conn,
                    "SELECT metadata FROM sources WHERE id = :id",
                    {"id": source_id},
                ).fetchone()
                current = res[0] if res else None
                if isinstance(current, str):
                    try:
                        cur_meta = json.loads(current)
                    except Exception:
                        cur_meta = {}
                elif current is None:
                    cur_meta = {}
                else:
                    cur_meta = current

                merged = dict(cur_meta or {})
                merged.update(updates or {})

                # Update sources metadata (handles RSS metadata persistence)
                safe_execute(
                    conn,
                    "UPDATE sources SET metadata = :meta WHERE id = :id",
                    {"meta": json.dumps(merged), "id": source_id},
                )
                logger.debug(
                    "Updated metadata for source %s: %s",
                    source_id,
                    updates,
                )
        except Exception:
            logger.debug(
                "Failed to update metadata for source %s",
                source_id,
            )

    def _reset_rss_failure_state(
        self,
        source_id: str | None,
    ) -> None:
        if not source_id:
            return
        now_iso = datetime.utcnow().isoformat()
        updates = {
            "rss_last_failed": now_iso,
            "rss_missing": None,
            "rss_consecutive_failures": 0,
        }
        self._update_source_meta(source_id, updates)

    def _increment_rss_failure(
        self,
        source_id: str | None,
    ) -> None:
        if not source_id:
            return
        try:
            dbm = DatabaseManager(self.database_url)
            with dbm.engine.connect() as conn:
                query = "SELECT metadata FROM sources WHERE id = :id"
                result = safe_execute(conn, query, {"id": source_id}).fetchone()

            cur_meta: dict[str, Any] = {}
            if result and result[0]:
                raw_meta = result[0]
                try:
                    cur_meta = json.loads(raw_meta)
                except Exception:
                    cur_meta = raw_meta or {}

            failure_count = 0
            if isinstance(cur_meta, dict):
                failure_count = cur_meta.get(
                    "rss_consecutive_failures",
                    0,
                )

            next_count = failure_count + 1
            updates = {
                "rss_consecutive_failures": next_count,
            }
            if next_count >= RSS_MISSING_THRESHOLD:
                updates["rss_missing"] = datetime.utcnow().isoformat()

            self._update_source_meta(source_id, updates)
        except Exception:
            missing_iso = datetime.utcnow().isoformat()
            self._update_source_meta(
                source_id,
                {"rss_missing": missing_iso},
            )

    def _get_existing_urls(self) -> set[str]:
        """Return existing URLs from candidate_links to avoid duplicates."""
        try:
            db_manager = DatabaseManager(self.database_url)

            with db_manager.engine.connect() as conn:
                result = safe_execute(conn, "SELECT url FROM candidate_links")
                urls: set[str] = set()
                for row in result.fetchall():
                    raw = row[0]
                    if not raw:
                        continue
                    urls.add(self._normalize_candidate_url(raw))
                return urls

        except Exception as e:
            logger.warning(f"Could not fetch existing URLs: {e}")
            return set()

    @staticmethod
    def _rss_retry_window_days(freq: str | None) -> int:
        """Return the number of days before retrying RSS after a miss.

        We interpret the declared publishing frequency into a conservative
        cooldown and cap it so that we always retry within a week. Missing
        or malformed frequencies fall back to a 7-day window.
        """

        try:
            days = parse_frequency_to_days(freq)
        except Exception:
            return 7

        window = int(round(days * 2))
        return max(2, min(7, window))

    def _is_recent_article(self, publish_date: datetime | None) -> bool:
        """Check if article was published within the date window."""
        if not publish_date:
            return True  # Include articles without dates (benefit of doubt)

        return publish_date >= self.cutoff_date

    def _get_existing_urls_for_source(self, source_id: str) -> set[str]:
        """Get existing URLs for a source to detect duplicates."""
        try:
            db_manager = DatabaseManager(self.database_url)
            with db_manager.engine.connect() as conn:
                result = safe_execute(
                    conn,
                    "SELECT url FROM candidate_links WHERE source_host_id = :source_id",
                    {"source_id": source_id},
                )
                urls: set[str] = set()
                for row in result.fetchall():
                    raw = row[0]
                    if not raw:
                        continue
                    urls.add(self._normalize_candidate_url(raw))
                return urls
        except Exception:
            logger.debug(f"Failed to get existing URLs for source {source_id}")
            return set()

    def _get_existing_article_count(self, source_id: str) -> int:
        """Count already-extracted articles for a source."""
        try:
            db_manager = DatabaseManager(self.database_url)
            with db_manager.engine.connect() as conn:
                result = safe_execute(
                    conn,
                    """
                        SELECT COUNT(a.id)
                        FROM articles a
                        JOIN candidate_links cl ON a.candidate_link_id = cl.id
                        WHERE cl.source_id = :source_id
                    """,
                    {"source_id": source_id},
                )
                row = result.fetchone()
                if row is None:
                    return 0
                return int(row[0] or 0)
        except Exception:
            logger.debug(
                "Failed to get existing article count for source %s",
                source_id,
            )
            return 0

    def _validate_dataset(
        self,
        dataset_label: str,
        db_manager: DatabaseManager,
    ) -> bool:
        """Validate that a dataset exists and has linked sources.

        Args:
            dataset_label: Dataset label to validate
            db_manager: Database manager instance

        Returns:
            True if dataset exists and has sources, False otherwise
        """
        try:
            with db_manager.engine.connect() as conn:
                # Check if dataset exists
                result = safe_execute(
                    conn,
                    "SELECT id, slug FROM datasets WHERE label = :label",
                    {"label": dataset_label},
                ).fetchone()

                if not result:
                    logger.error(f"❌ Dataset '{dataset_label}' not found in database")
                    # List available datasets to help user
                    available = safe_execute(
                        conn, "SELECT label FROM datasets ORDER BY label"
                    ).fetchall()
                    if available:
                        labels = [row[0] for row in available]
                        logger.info(f"Available datasets: {', '.join(labels)}")
                    else:
                        logger.info("No datasets found in database")
                    return False

                dataset_id = result[0]

                # Check if dataset has linked sources
                count_result = safe_execute(
                    conn,
                    """
                        SELECT COUNT(*)
                        FROM dataset_sources
                        WHERE dataset_id = :dataset_id
                    """,
                    {"dataset_id": dataset_id},
                ).fetchone()

                source_count = count_result[0] if count_result else 0

                if source_count == 0:
                    logger.warning(
                        f"⚠️  Dataset '{dataset_label}' has no linked sources"
                    )
                    return False

                logger.info(
                    f"✓ Dataset '{dataset_label}' validated: {source_count} sources"
                )
                return True

        except Exception as e:
            logger.error(f"Failed to validate dataset '{dataset_label}': {e}")
            return False

    def get_sources_to_process(
        self,
        dataset_label: str | None = None,
        limit: int | None = None,
        due_only: bool = True,
        host_filter: str | None = None,
        city_filter: str | None = None,
        county_filter: str | None = None,
        host_limit: int | None = None,
    ) -> tuple[pd.DataFrame, dict[str, int]]:
        """Retrieve sources from database that need URL discovery.

        Args:
            dataset_label: Filter by specific dataset
            limit: Maximum number of sources to process
            due_only: Whether to filter to only sources due for discovery
            host_filter: Exact host value to match
            city_filter: City name to match (case-insensitive)
            county_filter: County name to match (case-insensitive)
            host_limit: Maximum number of hosts to return after filtering

        Returns:
            Tuple of (DataFrame with source information, stats dict)
        """
        with DatabaseManager(self.database_url) as db:
            # Validate dataset_label when provided so callers get a clear
            # error when the label doesn't exist. Tests expect an error
            # to be logged and an empty result returned for invalid labels.
            if dataset_label:
                try:
                    from src.utils.dataset_utils import resolve_dataset_id

                    # resolve_dataset_id returns a UUID if found, otherwise
                    # raises ValueError which we surface as an ERROR log.
                    dataset_label = resolve_dataset_id(db.engine, dataset_label)
                except ValueError:
                    logger.error("Dataset '%s' not found", dataset_label)
                    # Also log available dataset labels to help the user find a
                    # valid value (tests expect this suggestion).
                    try:
                        # Use a fresh connection to list available datasets so we
                        # observe any recently committed rows.
                        with db.engine.begin() as conn:
                            stmt = text("SELECT label FROM datasets")
                            rows = safe_execute(conn, stmt).fetchall()
                        labels = [r[0] for r in rows if r and r[0]]
                        if labels:
                            logger.error("Available datasets: %s", ", ".join(labels))
                    except Exception as e:
                        # Best-effort only; don't fail if listing datasets fails.
                        logger.error(
                            "Failed to list available datasets for suggestion: %s",
                            str(e)
                        )

                    return pd.DataFrame(), {
                        "sources_available": 0,
                        "sources_due": 0,
                        "sources_skipped": 0,
                    }
            # Dataset validation may raise ValueError; handled above
            # TODO: Re-implement dataset validation using UUIDs

            # Use actual schema: id, host, host_norm, canonical_name,
            # city, county, owner, type, metadata
            # Prioritize sources that have never been attempted for discovery
            where_clauses = ["s.host IS NOT NULL", "s.host != ''"]
            params: dict[str, Any] = {}

            join_clause = ""
            if dataset_label:
                join_clause = (
                    "\nJOIN dataset_sources ds ON s.id = ds.source_id"
                    "\nJOIN datasets d ON ds.dataset_id = d.id"
                )
                where_clauses.append("(d.id = :dataset_id OR d.label = :dataset_label)")
                params["dataset_id"] = dataset_label  # UUID resolved above
                params["dataset_label"] = dataset_label  # Keep label as fallback

            if host_filter:
                where_clauses.append("LOWER(s.host) = :host_filter")
                params["host_filter"] = host_filter.lower()

            if city_filter:
                where_clauses.append("LOWER(s.city) = :city_filter")
                params["city_filter"] = city_filter.lower()

            if county_filter:
                where_clauses.append("LOWER(s.county) = :county_filter")
                params["county_filter"] = county_filter.lower()

            where_sql = " AND ".join(where_clauses)

            # Detect database dialect and build appropriate query
            dialect = db.engine.dialect.name

            if dialect == "postgresql":
                # PostgreSQL: Use DISTINCT ON for efficient deduplication
                # Subquery to get discovery_attempted flag per source
                query = f"""
                SELECT
                    s.id,
                    s.canonical_name as name,
                    'https://' || s.host as url,
                    s.metadata,
                    s.city,
                    s.county,
                    s.type as type_classification,
                    s.host,
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM candidate_links cl2
                            WHERE cl2.source_host_id = s.id
                        ) THEN 1
                        ELSE 0
                    END as discovery_attempted
                FROM sources s
                {join_clause}
                WHERE {where_sql}
                ORDER BY discovery_attempted ASC, s.canonical_name ASC
                """
            else:
                # SQLite: Use GROUP BY with aggregation
                query = f"""
                SELECT
                    s.id,
                    s.canonical_name as name,
                    'https://' || s.host as url,
                    s.metadata,
                    s.city,
                    s.county,
                    s.type as type_classification,
                    s.host,
                    MIN(CASE
                        WHEN cl.source_host_id IS NULL THEN 0
                        ELSE 1
                    END) as discovery_attempted
                FROM sources s
                LEFT JOIN candidate_links cl ON s.id = cl.source_host_id
                {join_clause}
                WHERE {where_sql}
                GROUP BY
                    s.id,
                    s.canonical_name,
                    s.host,
                    s.metadata,
                    s.city,
                    s.county,
                    s.type
                ORDER BY discovery_attempted ASC, s.canonical_name ASC
                """

            if limit:
                try:
                    safe_limit = int(limit)
                    if safe_limit > 0:
                        query += f" LIMIT {safe_limit}"
                except Exception:
                    pass

            # Use SQLAlchemy text() to ensure proper parameter binding for pg8000
            # SQLAlchemy converts :param to %s format required by pg8000

            logger.debug(f"Using {dialect} query syntax for get_sources_to_process")
            # Use SQLAlchemy text() for proper parameter binding with pg8000
            # pandas read_sql_query needs text() for named params with pg8000
            # (text is imported at module level)
            engine_for_pandas = getattr(db.engine, "_engine", db.engine)
            sql_text = text(query)
            df = pd.read_sql_query(sql_text, engine_for_pandas, params=params or None)

            # If requested, filter to only sources that are due for
            # discovery according to their declared frequency and the
            # most recent `candidate_links.processed_at` timestamp.
            sources_before_due_filter = len(df)
            sources_skipped = 0
            host_limited = 0

            if due_only and not df.empty:
                from .scheduling import should_schedule_discovery

                dbm = DatabaseManager(self.database_url)
                due_mask = []
                for _idx, row in df.iterrows():
                    try:
                        meta = None
                        raw_meta = (
                            row.get("metadata") if "metadata" in row.index else None
                        )
                        if raw_meta and isinstance(raw_meta, str):
                            try:
                                meta = json.loads(raw_meta)
                            except Exception:
                                meta = None
                        elif raw_meta and isinstance(raw_meta, dict):
                            meta = raw_meta

                        is_due = should_schedule_discovery(
                            dbm, str(row["id"]), source_meta=meta
                        )

                        # Log skip reasons for better debugging
                        if not is_due:
                            last_disc = meta.get("last_discovery_at") if meta else None
                            freq = meta.get("frequency") if meta else None
                            logger.debug(
                                "⏭️  Skipping %s: not due for discovery "
                                "(frequency=%s, last_discovery=%s)",
                                row.get("name", "unknown"),
                                freq,
                                last_disc,
                            )
                    except Exception as e:
                        # On error, default to scheduling the source.
                        # This avoids silent failures when metadata is malformed.
                        logger.warning(
                            "Error checking schedule for %s: %s. Scheduling anyway.",
                            row.get("name", "unknown"),
                            e,
                        )
                        is_due = True
                    due_mask.append(is_due)

                # Convert to a pandas Series conforming to df.index and filter
                try:
                    mask_series = pd.Series(due_mask, index=df.index)
                    df = df[mask_series]
                    sources_skipped = sources_before_due_filter - len(df)
                except Exception:
                    # If constructing the mask fails, fall back to original df
                    pass

            if host_limit and not df.empty:
                try:
                    safe_host_limit = int(host_limit)
                    if safe_host_limit > 0 and len(df) > safe_host_limit:
                        host_limited = len(df) - safe_host_limit
                        df = df.head(safe_host_limit)
                except Exception:
                    pass

            stats = {
                "sources_available": sources_before_due_filter,
                "sources_due": len(df),
                "sources_skipped": sources_skipped,
            }

            if host_limited:
                stats["sources_limited_by_host"] = host_limited

            return df, stats

    def discover_with_newspaper4k(
        self,
        source_url: str,
        source_id: str | None = None,
        operation_id: str | None = None,
        source_meta: dict | None = None,
        allow_build: bool = True,
        rss_already_attempted: bool = False,
    ) -> list[dict]:
        """Use newspaper4k to discover articles from a news source.

        OPTIMIZED VERSION: Focus on RSS discovery first; fallback to HTML

            Args:
                source_url: The base URL of the news source

            Returns:
                List of discovered article metadata
        """
        discovered_articles: list[dict[str, Any]] = []
        method_start_time = time.time()
        homepage_status_code: int | None = None

        def record_newspaper_effectiveness(
            status: DiscoveryMethodStatus,
            articles_found: int,
            *,
            status_codes: list[int] | None = None,
            notes: str | None = None,
        ) -> None:
            if not (self.telemetry and source_id and operation_id):
                return

            elapsed_ms = (time.time() - method_start_time) * 1000
            codes = status_codes or []
            try:
                self.telemetry.update_discovery_method_effectiveness(
                    source_id=source_id,
                    source_url=source_url,
                    discovery_method=DiscoveryMethod.NEWSPAPER4K,
                    status=status,
                    articles_found=articles_found,
                    response_time_ms=elapsed_ms,
                    status_codes=codes,
                    notes=notes,
                )
            except Exception:
                logger.debug(
                    "Failed to record newspaper4k telemetry for %s",
                    source_url,
                )

        try:
            from newspaper import Config  # type: ignore[import]

            # Create optimized config for faster discovery
            config = Config()
            config.browser_user_agent = self.user_agent
            config.request_timeout = 10  # HTTP request timeout
            config.number_threads = 1  # Single thread avoids warnings
            config.thread_timeout_seconds = 15  # Thread > request timeout
            config.verbose = False
            config.memoize_articles = False  # Don't cache to save memory

            logger.info(f"Building newspaper source for: {source_url}")

            # Quick homepage sniff: try to find RSS/Atom link tags on the
            # site's root page and prefer RSS discovery (much faster than
            # building the whole newspaper index which can hit many URLs).
            # If the source metadata indicates `rss_missing` was recently
            # set, avoid probing for or following RSS/feed-like links here
            # to prevent unnecessary feed fetches that are known to fail.
            try:
                homepage_request_start = time.time()
                resp = self.session.get(source_url, timeout=min(5, self.timeout))
                homepage_status_code = getattr(resp, "status_code", None)
                homepage_fetch_ms = (time.time() - homepage_request_start) * 1000
                html = resp.text or ""

                source_meta_dict = (
                    source_meta if isinstance(source_meta, dict) else None
                )

                skip_internal_feed_probe = False
                rss_missing_active = False
                if source_meta_dict:
                    rss_missing_active = bool(source_meta_dict.get("rss_missing"))
                    try:
                        skip_internal_feed_probe, _, _ = (
                            self._should_skip_rss_from_meta(source_meta_dict)
                        )
                    except Exception:
                        skip_internal_feed_probe = rss_missing_active

                if rss_already_attempted:
                    skip_internal_feed_probe = True

                feeds: list[str] = []
                if not skip_internal_feed_probe:
                    try:
                        feeds = self._extract_homepage_feed_urls(
                            html,
                            source_url,
                        )
                    except Exception:
                        feeds = []

                if feeds:
                    logger.info(
                        ("Found %d feed(s) on homepage; trying those first")
                        % (len(feeds),)
                    )
                    _rss_ret = self.discover_with_rss_feeds(
                        source_url,
                        source_id,
                        operation_id,
                        custom_rss_feeds=feeds,
                    )
                    if isinstance(_rss_ret, tuple) and len(_rss_ret) == 2:
                        rss_results, rss_summary = _rss_ret
                    else:
                        rss_results = _rss_ret or []

                    if rss_results:
                        logger.info(
                            (
                                "Homepage RSS discovery returned %d "
                                "articles, skipping newspaper.build"
                            )
                            % (len(rss_results),)
                        )
                        record_newspaper_effectiveness(
                            DiscoveryMethodStatus.SUCCESS,
                            len(rss_results),
                            status_codes=(
                                [homepage_status_code]
                                if homepage_status_code is not None
                                else None
                            ),
                            notes="homepage RSS link probe",
                        )
                        return rss_results

                try:
                    homepage_candidates = self._extract_homepage_article_candidates(
                        html,
                        source_url,
                        rss_missing=rss_missing_active,
                        max_candidates=min(
                            self.max_articles_per_source,
                            25,
                        ),
                    )
                except Exception:
                    homepage_candidates = []

                if homepage_candidates:
                    logger.info(
                        "Homepage link-scan found %d candidate URLs; "
                        "returning those instead of building",
                        len(homepage_candidates),
                    )
                    existing_urls = self._get_existing_urls()
                    out = []
                    discovered_at = datetime.utcnow().isoformat()
                    for u in homepage_candidates:
                        normalized_candidate = self._normalize_candidate_url(u)
                        if normalized_candidate in existing_urls:
                            continue

                        out.append(
                            {
                                "url": u,
                                "source_url": source_url,
                                "discovery_method": "homepage_links",
                                "discovered_at": discovered_at,
                                "metadata": {"homepage_sniff": True},
                            }
                        )
                        existing_urls.add(normalized_candidate)
                    if out:
                        record_newspaper_effectiveness(
                            DiscoveryMethodStatus.SUCCESS,
                            len(out),
                            status_codes=(
                                [homepage_status_code]
                                if homepage_status_code is not None
                                else None
                            ),
                            notes=(
                                "homepage link-scan"
                                f" ({len(out)} candidates, "
                                f"fetch ~{homepage_fetch_ms:.0f}ms)"
                            ),
                        )
                        return out
            except Exception:
                # Non-fatal — if homepage sniff fails, fall back to build
                pass

            # If building the full newspaper index is disabled (for
            # example, because RSS was recently marked missing), avoid
            # invoking `newspaper.build` which may spawn many requests
            # including feed-like endpoints. Continue to the lighter
            # homepage sniff/link-scan above and return those candidates
            # if present.
            if not allow_build:
                logger.info(
                    "newspaper4k full build disabled by caller; returning "
                    "homepage candidates only"
                )
                paper = None
            else:
                # Disable image fetching to reduce network I/O while building
                # (some sites load many images during discovery otherwise).
                try:
                    config.fetch_images = False
                except Exception:
                    # Not all newspaper versions expose this attribute; ignore
                    # if missing
                    pass

                # Build with timeout limits and fewer threads. Running
                # `newspaper.build` in a separate process ensures we can
                # reliably terminate it if it hangs or takes too long. The
                # child process will write discovered article URLs to a
                # temporary file which we then read back here. This avoids
                # the ThreadPoolExecutor shutdown/join blocking issue.
                build_timeout = min(30, max(10, int(self.timeout * 3)))
                paper = None
                try:
                    # Use multiprocessing to isolate the build and allow
                    # forcible termination on timeout. We avoid passing
                    # complex objects into the child process by sending
                    # only a simple boolean flag for image fetching so the
                    # worker constructs its own `Config` instance.
                    import os
                    import tempfile
                    from multiprocessing import Process

                    tmpf = tempfile.NamedTemporaryFile(delete=False)
                    tmp_path = tmpf.name
                    tmpf.close()

                    fetch_images_flag = False
                    try:
                        # config may omit fetch_images; default to False
                        fetch_images_flag = bool(getattr(config, "fetch_images", False))
                    except Exception:
                        fetch_images_flag = False

                    # Choose proxy for this source
                    proxy = None
                    if self.proxy_pool:
                        proxy = random.choice(self.proxy_pool)

                    proc = Process(
                        target=_newspaper_build_worker,
                        args=(source_url, tmp_path, fetch_images_flag, proxy),
                    )
                    proc.start()
                    proc.join(timeout=build_timeout)
                    if proc.is_alive():
                        logger.warning(
                            "newspaper.build timed out after %ds for %s",
                            build_timeout,
                            source_url,
                        )
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        proc.join(timeout=5)

                    # Read URLs back from the temporary file
                    try:
                        import pickle as _pickle

                        with open(tmp_path, "rb") as fh:
                            urls = _pickle.load(fh)
                    except Exception:
                        urls = []
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

                    # Create a lightweight fake `paper` object with
                    # `articles` containing objects with a `url` attribute
                    class _FakeArticle:
                        def __init__(self, url):
                            self.url = url

                    class _FakePaper:
                        def __init__(self, urls):
                            self.articles = [_FakeArticle(u) for u in (urls or [])]

                    paper = _FakePaper(urls)

                except Exception as e:
                    logger.warning(f"newspaper4k build raised for {source_url}: {e}")

            # Don't download all articles - just get the URLs
            articles_attr: list[Any] = []
            if paper is not None:
                articles_attr = getattr(paper, "articles", []) or []
            article_count = len(articles_attr)
            logger.info("Found %d potential articles" % (article_count,))

            if article_count == 0:
                logger.warning("No articles found via newspaper4k for %s", source_url)
                record_newspaper_effectiveness(
                    DiscoveryMethodStatus.NO_FEED,
                    0,
                    status_codes=(
                        [homepage_status_code]
                        if homepage_status_code is not None
                        else None
                    ),
                    notes="newspaper.build returned 0 articles",
                )
                return discovered_articles

            # Get existing URLs to prevent duplicates
            existing_urls = self._get_existing_urls()

            # Limit processing and don't download full content
            articles_to_process = articles_attr[: min(self.max_articles_per_source, 25)]

            for article in articles_to_process:
                try:
                    normalized_article_url = self._normalize_candidate_url(article.url)

                    # Skip if URL already exists
                    if normalized_article_url in existing_urls:
                        logger.debug(f"Skipping duplicate URL: {article.url}")
                        continue

                    # Only get basic metadata without downloading content
                    article_data = {
                        "url": article.url,
                        "source_url": source_url,
                        "discovery_method": "newspaper4k",
                        "discovered_at": datetime.utcnow().isoformat(),
                        "metadata": {
                            "newspaper_source_url": source_url,
                            "article_count": article_count,
                        },
                    }

                    # Skip individual article downloads for speed
                    # Just collect URLs for now - content can be fetched later
                    discovered_articles.append(article_data)
                    existing_urls.add(normalized_article_url)

                except Exception as article_error:
                    msg = f"Error processing article from {source_url}"
                    logger.warning(f"{msg}: {article_error}")
                    continue

            logger.info(
                "newspaper4k found %d articles",
                len(discovered_articles),
            )

            record_newspaper_effectiveness(
                DiscoveryMethodStatus.SUCCESS,
                len(discovered_articles),
                status_codes=(
                    [homepage_status_code] if homepage_status_code is not None else None
                ),
                notes="newspaper.build",
            )

        except Exception as e:
            msg = "Failed to discover articles with newspaper4k"
            logger.error(f"{msg} for {source_url}: {e}")
            record_newspaper_effectiveness(
                DiscoveryMethodStatus.SERVER_ERROR,
                len(discovered_articles),
                notes=str(e)[:200],
            )

        return discovered_articles

    def _format_discovered_by(self, article_data: dict) -> str:
        """Return a concise, descriptive label for how this URL was discovered.

        The label is intended for storage in
        `candidate_links.discovered_by` and should be short but distinctive.
        For example, include feed host or method detail when available.
        """
        method = (
            article_data.get("discovery_method")
            or article_data.get("method")
            or "unknown"
        )

        # Normalize enums and common string variants
        method_val = getattr(method, "value", method)
        if not isinstance(method_val, str):
            method_val = str(method_val)

        # Attempt to include feed URL or source of discovery for disambiguation
        details = None
        meta = article_data.get("metadata") or article_data.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        for k in ("feed_url", "rss_feed", "feed", "source_feed"):
            if k in article_data and article_data[k]:
                details = article_data[k]
                break
            if k in meta and meta[k]:
                details = meta[k]
                break

        # Shorten detail to host + path fragment if possible
        label = f"discovery.{method_val}"
        if details:
            try:
                p = urlparse(details)
                host = p.netloc or p.path
                path = p.path or ""
                short = f"{host}{path}"
                if len(short) > 60:
                    short = short[:57] + "..."
                label = f"{label}[{short}]"
            except Exception:
                short = str(details)
                if len(short) > 60:
                    short = short[:57] + "..."
                label = f"{label}[{short}]"

        return label

    def discover_with_storysniffer(
        self,
        source_url: str,
        source_id: str | None = None,
        operation_id: str | None = None,
    ) -> list[dict]:
        """Attempt to use StorySniffer for article URL discovery.

        NOTE: StorySniffer 1.0.9+ is a URL classifier, not a web crawler.
        Its guess() method returns a boolean indicating if a single URL is
        likely an article, rather than discovering article URLs from a homepage.

        This method currently cannot discover articles from homepage URLs using
        StorySniffer alone. It would need to:
        1. Fetch and parse the homepage HTML
        2. Extract all links from the page
        3. Classify each link using StorySniffer.guess()

        For now, this method is effectively disabled and returns no articles.

        Args:
            source_url: The base URL of the news source

        Returns:
            Empty list (StorySniffer cannot discover URLs from homepages)
        """
        discovered_articles: list[dict[str, Any]] = []
        method_start_time = time.time()

        def record_storysniffer_effectiveness(
            status: DiscoveryMethodStatus,
            articles_found: int,
            *,
            notes: str | None = None,
        ) -> None:
            if not (self.telemetry and source_id and operation_id):
                return

            elapsed_ms = (time.time() - method_start_time) * 1000
            try:
                self.telemetry.update_discovery_method_effectiveness(
                    source_id=source_id,
                    source_url=source_url,
                    discovery_method=DiscoveryMethod.STORYSNIFFER,
                    status=status,
                    articles_found=articles_found,
                    response_time_ms=elapsed_ms,
                    status_codes=[],
                    notes=notes,
                )
            except Exception:
                logger.debug(
                    "Failed to record storysniffer telemetry for %s",
                    source_url,
                )

        if not self.storysniffer:
            logger.debug("StorySniffer not available, skipping")
            record_storysniffer_effectiveness(
                DiscoveryMethodStatus.SKIPPED,
                0,
                notes="storysniffer unavailable",
            )
            return discovered_articles

        # StorySniffer.guess() is a classifier (returns bool), not a crawler
        # It cannot discover article URLs from a homepage without:
        # 1. Fetching the homepage HTML
        # 2. Extracting all links
        # 3. Classifying each link individually
        #
        # This would duplicate work done by newspaper4k and RSS methods.
        # For now, skip StorySniffer for discovery and return empty results.
        logger.debug(
            "StorySniffer is a URL classifier, not a discovery crawler. "
            "Skipping discovery for: %s",
            source_url,
        )
        record_storysniffer_effectiveness(
            DiscoveryMethodStatus.SKIPPED,
            0,
            notes="storysniffer.guess() is a classifier (returns bool), not a crawler",
        )
        return discovered_articles

    def discover_with_rss_feeds(
        self,
        source_url: str,
        source_id: str | None = None,
        operation_id: str | None = None,
        custom_rss_feeds: list[str] | None = None,
        source_meta: dict | None = None,
    ) -> tuple[list[dict], dict]:
        """Attempt to discover RSS feeds and extract article URLs - OPTIMIZED.

        Args:
            source_url: Base URL of the news source.
            custom_rss_feeds: Optional list of known RSS feed URLs
                for this source.

        Returns:
            List of discovered article metadata from RSS feeds
        """
        discovered_articles: list[dict[str, Any]] = []
        start_time = time.time()
        feeds_tried = 0
        feeds_successful = 0
        duplicate_count = 0
        old_article_count = 0
        network_error_count = 0

        # Build candidate feed list (custom first, then common paths)
        potential_feeds: list[str] = []
        if custom_rss_feeds:
            for f in custom_rss_feeds:
                potential_feeds.append(f)
                if isinstance(f, str) and f.startswith("http://"):
                    potential_feeds.append(f.replace("http://", "https://", 1))

        potential_feeds.extend(
            [
                urljoin(source_url, "/rss"),
                urljoin(source_url, "/feed"),
                urljoin(source_url, "/rss.xml"),
                urljoin(source_url, "/feed.xml"),
                urljoin(source_url, "/index.xml"),
                urljoin(source_url, "/atom.xml"),
                urljoin(source_url, "/news/rss"),
                urljoin(source_url, "/news/feed"),
                urljoin(source_url, "/feeds/all"),
                urljoin(source_url, "/rss/all"),
            ]
        )

        try:
            # Try each feed URL sequentially and bail out when a working
            # feed is found.
            for feed_url in potential_feeds:
                feeds_tried += 1
                logger.debug("Trying RSS feed: %s", feed_url)

                response_start = time.time()
                try:
                    response = self.session.get(feed_url, timeout=self.timeout)
                except requests.exceptions.Timeout:
                    network_error_count += 1
                    response_time_ms = (time.time() - response_start) * 1000
                    if self.telemetry and source_id and operation_id:
                        self.telemetry.track_http_status(
                            operation_id=operation_id,
                            source_id=source_id,
                            source_url=source_url,
                            discovery_method=DiscoveryMethod.RSS_FEED,
                            attempted_url=feed_url,
                            status_code=408,
                            response_time_ms=response_time_ms,
                            error_message=("Timeout after %ds" % (self.timeout,)),
                        )
                    logger.warning(
                        "RSS feed request timed out after %ds: %s",
                        self.timeout,
                        feed_url,
                    )
                    continue
                except requests.exceptions.ConnectionError:
                    network_error_count += 1
                    response_time_ms = (time.time() - response_start) * 1000
                    if self.telemetry and source_id and operation_id:
                        self.telemetry.track_http_status(
                            operation_id=operation_id,
                            source_id=source_id,
                            source_url=source_url,
                            discovery_method=DiscoveryMethod.RSS_FEED,
                            attempted_url=feed_url,
                            status_code=0,
                            response_time_ms=response_time_ms,
                            error_message="Connection error",
                        )
                    logger.warning("Connection error for RSS feed: %s", feed_url)
                    continue
                except Exception as e:
                    network_error_count += 1
                    response_time_ms = (time.time() - response_start) * 1000
                    if self.telemetry and source_id and operation_id:
                        self.telemetry.track_http_status(
                            operation_id=operation_id,
                            source_id=source_id,
                            source_url=source_url,
                            discovery_method=DiscoveryMethod.RSS_FEED,
                            attempted_url=feed_url,
                            status_code=0,
                            response_time_ms=response_time_ms,
                            error_message=str(e),
                        )
                    logger.debug("Error fetching RSS feed %s: %s", feed_url, e)
                    continue

                # At this point we have a response object
                response_time_ms = (time.time() - response_start) * 1000
                if self.telemetry and source_id and operation_id:
                    try:
                        self.telemetry.track_http_status(
                            operation_id=operation_id,
                            source_id=source_id,
                            source_url=source_url,
                            discovery_method=DiscoveryMethod.RSS_FEED,
                            attempted_url=feed_url,
                            status_code=response.status_code,
                            response_time_ms=response_time_ms,
                            content_length=len(getattr(response, "content", b"")),
                        )
                    except Exception as e:
                        logger.debug(
                            "Failed to record HTTP status telemetry for %s: %s",
                            feed_url,
                            str(e),
                        )

                # Handle HTTP status codes with special cases so we don't
                # incorrectly mark feeds as permanently missing when the
                # site is rate-limiting us or experiencing a transient
                # outage. Treat throttling (429), authorization blocks
                # (401/403), and 5xx responses as network-style errors to
                # avoid incrementing the permanent failure counter.
                status = response.status_code
                if status == 404:
                    logger.debug("RSS feed not found (404): %s", feed_url)
                    continue

                if status in (401, 403, 429) or status >= 500:
                    network_error_count += 1
                    logger.warning(
                        "Transient RSS error %s for %s",
                        status,
                        feed_url,
                    )
                    continue

                if status not in (200, 301, 302):
                    logger.debug(
                        "RSS feed returned status %s: %s",
                        status,
                        feed_url,
                    )
                    continue

                # Parse feed
                try:
                    feed = feedparser.parse(response.content)
                except Exception as e:
                    network_error_count += 1
                    logger.debug("feedparser failed for %s: %s", feed_url, e)
                    continue

                # If feed has entries, process them
                if getattr(feed, "entries", None) and len(feed.entries) > 0:
                    feeds_successful += 1
                    entry_count = len(feed.entries)
                    logger.info(
                        "Found RSS feed with %d entries: %s",
                        entry_count,
                        feed_url,
                    )

                    existing_urls = self._get_existing_urls()
                    start_len = len(discovered_articles)

                    for entry in feed.entries[: self.max_articles_per_source]:
                        if not entry.get("link"):
                            continue
                        article_url = entry.get("link")
                        normalized_article_url = (
                            self._normalize_candidate_url(article_url)
                            if article_url
                            else None
                        )

                        if normalized_article_url in existing_urls:
                            duplicate_count += 1
                            continue

                        publish_date = None
                        if entry.get("published_parsed"):
                            try:
                                publish_date = datetime(*entry.published_parsed[:6])
                            except Exception:
                                publish_date = None

                        if not self._is_recent_article(publish_date):
                            old_article_count += 1
                            continue

                        article_data = {
                            "url": article_url,
                            "source_url": source_url,
                            "discovery_method": "rss_feed",
                            "discovered_at": datetime.utcnow().isoformat(),
                            "title": (entry.get("title") or "").strip(),
                            "metadata": {
                                "rss_feed_url": feed_url,
                                "feed_entry_count": entry_count,
                                "rss_entry_data": {
                                    "summary": entry.get("summary", ""),
                                    "published": entry.get("published", ""),
                                    "author": entry.get("author", ""),
                                },
                            },
                        }

                        if publish_date:
                            article_data["publish_date"] = publish_date.isoformat()

                        discovered_articles.append(article_data)
                        if normalized_article_url:
                            existing_urls.add(normalized_article_url)

                    # Fallback: if feed had entries but all filtered out,
                    # optionally include a small recent set
                    if len(discovered_articles) == start_len and entry_count > 0:
                        recent_activity_days = 90
                        try:
                            freq = None
                            if source_meta and isinstance(source_meta, dict):
                                freq = source_meta.get("frequency") or source_meta.get(
                                    "freq"
                                )
                            if freq:
                                parsed = parse_frequency_to_days(freq)
                                recent_activity_days = max(1, int(parsed * 3))
                        except Exception:
                            recent_activity_days = 90

                        most_recent = None
                        try:
                            if getattr(feed, "feed", None) and feed.feed.get(
                                "updated_parsed"
                            ):
                                most_recent = datetime(*feed.feed.updated_parsed[:6])
                            for entry in feed.entries:
                                if entry.get("published_parsed"):
                                    try:
                                        d = datetime(*entry.published_parsed[:6])
                                        if not most_recent or d > most_recent:
                                            most_recent = d
                                    except Exception:
                                        continue
                        except Exception:
                            most_recent = None

                        allow_fallback = False
                        if most_recent:
                            try:
                                threshold = datetime.utcnow() - timedelta(
                                    days=recent_activity_days
                                )
                                allow_fallback = most_recent >= threshold
                            except Exception:
                                allow_fallback = False

                        if allow_fallback:
                            fallback_count = min(5, self.max_articles_per_source)
                            for entry in feed.entries[:fallback_count]:
                                article_url = entry.get("link")
                                normalized_article_url = (
                                    self._normalize_candidate_url(article_url)
                                    if article_url
                                    else None
                                )

                                if (
                                    not article_url
                                    or normalized_article_url in existing_urls
                                ):
                                    continue
                                article_data = {
                                    "url": article_url,
                                    "source_url": source_url,
                                    "discovery_method": "rss_feed",
                                    "discovered_at": (datetime.utcnow().isoformat()),
                                    "title": ((entry.get("title") or "").strip()),
                                    "metadata": {
                                        "rss_feed_url": feed_url,
                                        "feed_entry_count": entry_count,
                                        "fallback_include_older": True,
                                    },
                                }
                                if entry.get("published_parsed"):
                                    try:
                                        pd = datetime(*entry.published_parsed[:6])
                                        article_data["publish_date"] = pd.isoformat()
                                    except Exception:
                                        pass
                                discovered_articles.append(article_data)
                                if normalized_article_url:
                                    existing_urls.add(normalized_article_url)

                    logger.info(
                        "RSS discovery found %d articles",
                        len(discovered_articles),
                    )
                    break

        except ImportError:
            logger.warning("feedparser not available for RSS discovery")
        except Exception as e:
            logger.error(f"RSS discovery failed for {source_url}: {e}")

        # Log RSS discovery summary
        if feeds_tried == 0:
            logger.info(f"RSS discovery skipped for {source_url}")
        elif feeds_successful == 0:
            logger.warning(
                "RSS discovery failed for %s: tried %d potential feed URLs, "
                "none worked",
                source_url,
                feeds_tried,
            )

        discovery_time = time.time() - start_time
        logger.info(
            "RSS discovery completed in %.2fs: tried %d feeds, %d successful, "
            "found %d articles, filtered %d duplicates, %d old articles",
            discovery_time,
            feeds_tried,
            feeds_successful,
            len(discovered_articles),
            duplicate_count,
            old_article_count,
        )

        if self.telemetry and source_id and operation_id:
            if len(discovered_articles) > 0:
                status = DiscoveryMethodStatus.SUCCESS
            elif feeds_tried == 0:
                status = DiscoveryMethodStatus.NO_FEED
            elif feeds_successful == 0:
                status = DiscoveryMethodStatus.NO_FEED
            else:
                status = DiscoveryMethodStatus.PARSE_ERROR

            status_codes = []
            if feeds_tried > 0:
                if feeds_successful > 0:
                    status_codes.append(200)
                else:
                    status_codes.append(404)

            try:
                self.telemetry.update_discovery_method_effectiveness(
                    source_id=source_id,
                    source_url=source_url,
                    discovery_method=DiscoveryMethod.RSS_FEED,
                    status=status,
                    articles_found=len(discovered_articles),
                    response_time_ms=discovery_time * 1000,
                    status_codes=status_codes,
                    notes=(
                        "Tried %d feeds, %d successful"
                        % (feeds_tried, feeds_successful)
                    ),
                )
            except Exception as e:
                logger.warning(
                    "Failed to update RSS telemetry for source %s: %s",
                    source_id,
                    str(e),
                )

        summary = {
            "feeds_tried": feeds_tried,
            "feeds_successful": feeds_successful,
            "network_errors": network_error_count,
        }

        return discovered_articles, summary

    def process_source(
        self,
        source_row: pd.Series,
        dataset_label: str | None = None,
        operation_id: str | None = None,
    ) -> DiscoveryResult:
        """Process a single source and store discovered URLs."""

        from .source_processing import SourceProcessor

        processor = SourceProcessor(
            discovery=self,
            source_row=source_row,
            dataset_label=dataset_label,
            operation_id=operation_id,
            date_parser=_parse_date,
        )
        return processor.process()

    def run_discovery(
        self,
        dataset_label: str | None = None,
        source_limit: int | None = None,
        source_filter: str | None = None,
        source_uuids: list[str] | None = None,
        due_only: bool = False,
        host_filter: str | None = None,
        city_filter: str | None = None,
        county_filter: str | None = None,
        host_limit: int | None = None,
        existing_article_limit: int | None = None,
    ) -> dict[str, int]:
        """Run the complete discovery pipeline.

        Args:
            dataset_label: Dataset label for filtering and tagging
            source_limit: Maximum number of sources to process
            source_filter: Optional filter for source name/URL
            source_uuids: Optional list of specific source UUIDs to process
            due_only:
                Whether to respect scheduling (default False to allow
                caller control)
            host_filter: Exact host value to match
            city_filter: City name filter (case-insensitive)
            county_filter: County name filter (case-insensitive)
            host_limit: Maximum number of hosts to process
            existing_article_limit:
                Skip sources with greater-or-equal existing article counts

        Returns:
            Dictionary with processing statistics
        """
        logger.info("Starting URL discovery pipeline")

        # Start telemetry tracking
        with self.telemetry.track_operation(
            OperationType.CRAWL_DISCOVERY,
            dataset_label=dataset_label,
            source_limit=source_limit,
            source_filter=source_filter,
            days_back=self.days_back,
        ) as tracker:
            # Get sources to process (respect `due_only` scheduling)
            sources_df, source_stats = self.get_sources_to_process(
                dataset_label=dataset_label,
                limit=source_limit,
                due_only=due_only,
                host_filter=host_filter,
                city_filter=city_filter,
                county_filter=county_filter,
                host_limit=host_limit,
            )

            # Apply UUID filtering first (most specific)
            if source_uuids:
                logger.info(f"Filtering sources by UUIDs: {source_uuids}")
                sources_df = sources_df[sources_df["id"].isin(source_uuids)]
                if len(sources_df) == 0:
                    logger.warning("No sources found with the specified UUIDs")
                    return {
                        "sources_processed": 0,
                        "total_candidates_discovered": 0,
                        "sources_failed": 0,
                        "sources_succeeded": 0,
                    }
            elif source_filter:
                # Filter by source name or URL (fallback)
                mask = sources_df["name"].str.contains(
                    source_filter,
                    case=False,
                    na=False,
                ) | sources_df["url"].str.contains(
                    source_filter,
                    case=False,
                    na=False,
                )
                sources_df = sources_df[mask]

            # Print source stats immediately to stdout
            print("📊 Source Discovery Status:")
            print(f"   Sources available: {source_stats.get('sources_available', 0)}")
            print(f"   Sources due for discovery: {source_stats.get('sources_due', 0)}")
            if source_stats.get("sources_skipped", 0) > 0:
                skipped = source_stats.get("sources_skipped", 0)
                print(f"   Sources skipped (not due): {skipped}")
            print(f"   Sources to process: {len(sources_df)}")
            print()

            logger.info(f"Processing {len(sources_df)} sources")

            # Initialize telemetry metrics
            metrics = OperationMetrics(
                total_items=len(sources_df), processed_items=0, failed_items=0
            )

            stats = {
                "sources_processed": 0,
                "total_candidates_discovered": 0,
                "sources_failed": 0,
                "sources_succeeded": 0,
                "sources_with_content": 0,  # Sources finding >=1 article
                "sources_no_content": 0,  # Sources that found 0 articles
            }

            if source_stats.get("sources_limited_by_host"):
                stats["sources_limited_by_host"] = source_stats[
                    "sources_limited_by_host"
                ]

            # (scheduling/due-only filtering is handled by
            # `get_sources_to_process` when `due_only=True` is passed)

            for idx, source_row in sources_df.iterrows():
                if existing_article_limit is not None and existing_article_limit >= 0:
                    try:
                        existing_count = self._get_existing_article_count(
                            str(source_row.get("id"))
                        )
                    except Exception:
                        existing_count = 0

                    if existing_count >= existing_article_limit:
                        stats.setdefault("sources_skipped_existing", 0)
                        stats["sources_skipped_existing"] += 1
                        logger.info(
                            "Skipping %s: %s existing articles (limit=%s)",
                            source_row.get("name"),
                            existing_count,
                            existing_article_limit,
                        )
                        continue

                try:
                    discovery_result = self.process_source(
                        source_row,
                        dataset_label,
                        tracker.operation_id,
                    )

                    # Record detailed discovery outcome for telemetry
                    self.telemetry.record_discovery_outcome(
                        operation_id=tracker.operation_id,
                        source_id=str(source_row.get("id", "")),
                        source_name=str(source_row.get("name", "Unknown")),
                        source_url=str(source_row.get("url", "")),
                        discovery_result=discovery_result,
                    )

                    stats["sources_processed"] += 1
                    stats[
                        "total_candidates_discovered"
                    ] += discovery_result.articles_new

                    # Track different types of success
                    if discovery_result.is_technical_failure:
                        stats["sources_failed"] += 1
                    else:
                        stats["sources_succeeded"] += 1

                    # Track content success separately
                    if discovery_result.articles_new > 0:
                        stats["sources_with_content"] += 1
                    else:
                        stats["sources_no_content"] += 1

                    # Update telemetry
                    tracker.update_progress(
                        processed=metrics.processed_items,
                        total=metrics.total_items,
                        message=(f"Processed {source_row['name']}"),
                    )

                    # Print progress to stdout for real-time visibility
                    print(
                        f"✓ [{stats['sources_processed']}/{len(sources_df)}] "
                        f"{source_row['name']}: "
                        f"{discovery_result.articles_new} new URLs"
                    )

                    logger.info(
                        f"Progress: {stats['sources_processed']}/"
                        f"{len(sources_df)} sources"
                    )

                    # Respectful delay between sources
                    time.sleep(self.delay)

                    # Only persist last_discovery_at if we actually found and
                    # successfully stored new URLs. This prevents sources from
                    # being marked as "discovered" when the process fails before
                    # saving to candidate_links table.
                    should_mark_discovered = (
                        discovery_result.articles_new > 0
                        and not discovery_result.is_technical_failure
                    )
                    if should_mark_discovered:
                        try:
                            self._update_source_meta(
                                source_row.get("id"),
                                {
                                    "last_discovery_at": datetime.utcnow().isoformat(),
                                },
                            )
                        except Exception:
                            # Don't let metadata write failures interrupt discovery
                            logger.debug(
                                "Failed to persist last_discovery_at for %s",
                                source_row.get("id"),
                            )

                except Exception as e:
                    # Print error to stdout for visibility
                    print(
                        f"✗ [{stats['sources_processed'] + 1}/{len(sources_df)}] "
                        f"{source_row.get('name')}: ERROR - {str(e)[:100]}"
                    )

                    logger.error(
                        "Failed to process source %s: %s",
                        source_row.get("name"),
                        e,
                    )
                    stats["sources_failed"] += 1
                    stats["sources_processed"] += 1

                    # Record source failure in telemetry
                    self.telemetry.record_site_failure(
                        operation_id=tracker.operation_id,
                        site_url=source_row.get("url", ""),
                        error=e,
                        site_name=source_row.get("name", "Unknown"),
                        discovery_method="process_source",
                    )

                    # Update telemetry for failure
                    tracker.update_progress(
                        processed=metrics.processed_items,
                        total=metrics.total_items,
                        message=(f"Failed: {source_row.get('name', 'Unknown')}"),
                    )

            logger.info(
                "Discovery complete. Processed %s sources, found %s candidate URLs",
                stats["sources_processed"],
                stats["total_candidates_discovered"],
            )

            # Add scheduling stats to the return dictionary
            stats.update(source_stats)

            return stats


def get_sources_from_db(db_manager, dataset_id=None, limit=None):
    """Get sources from the database for discovery.

    Args:
        db_manager: DatabaseManager instance
        dataset_id: Optional dataset ID to filter sources
        limit: Optional limit on number of sources to return

    Returns:
        List of source dictionaries with 'id', 'host', 'canonical_name'
    """
    from sqlalchemy import MetaData, Table, select

    try:
        metadata = MetaData()
        sources_tbl = Table(
            "sources",
            metadata,
            autoload_with=db_manager.engine,
        )

        if dataset_id:
            # Join with dataset_sources to filter by dataset
            ds_tbl = Table(
                "dataset_sources",
                metadata,
                autoload_with=db_manager.engine,
            )
            query = (
                select(
                    sources_tbl.c.id,
                    sources_tbl.c.host,
                    sources_tbl.c.canonical_name,
                )
                .select_from(
                    sources_tbl.join(
                        ds_tbl,
                        sources_tbl.c.id == ds_tbl.c.source_id,
                    )
                )
                .where(ds_tbl.c.dataset_id == dataset_id)
            )
        else:
            query = select(
                sources_tbl.c.id,
                sources_tbl.c.host,
                sources_tbl.c.canonical_name,
            )

        if limit:
            query = query.limit(limit)

        result = safe_session_execute(db_manager.session, query).fetchall()
        return [
            {
                "id": row["id"],
                "host": row["host"],
                "canonical_name": row["canonical_name"],
                "url": f"https://{row['host']}",
            }
            for row in result
        ]

    except Exception as e:
        logger.error(f"Error querying sources: {e}")
        return []


def run_discovery_pipeline(
    dataset_label: str | None = None,
    source_limit: int | None = None,
    source_filter: str | None = None,
    source_uuids: list[str] | None = None,
    database_url: str | None = None,
    max_articles_per_source: int = 50,
    days_back: int = 7,
    host_filter: str | None = None,
    city_filter: str | None = None,
    county_filter: str | None = None,
    host_limit: int | None = None,
    existing_article_limit: int | None = None,
) -> dict[str, int]:
    """Convenience function to run the discovery pipeline.

    Args:
        dataset_label: Dataset label for filtering and tagging
        source_limit: Maximum number of sources to process
        source_filter: Optional filter for source name/URL
        source_uuids: Optional list of specific source UUIDs to process
        database_url: Database connection string
        max_articles_per_source: Maximum articles to discover per source
        days_back: How many days back to look for recent articles

    Returns:
        Dictionary with processing statistics
    """
    discovery = NewsDiscovery(
        database_url=database_url,
        max_articles_per_source=max_articles_per_source,
        days_back=days_back,
    )

    return discovery.run_discovery(
        dataset_label=dataset_label,
        source_limit=source_limit,
        source_filter=source_filter,
        source_uuids=source_uuids,
        host_filter=host_filter,
        city_filter=city_filter,
        county_filter=county_filter,
        host_limit=host_limit,
        existing_article_limit=existing_article_limit,
    )


if __name__ == "__main__":
    # Example usage
    import sys

    logging.basicConfig(level=logging.INFO)

    dataset_label = sys.argv[1] if len(sys.argv) > 1 else "test-discovery"
    source_limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    stats = run_discovery_pipeline(
        dataset_label=dataset_label, source_limit=source_limit
    )

    print("\nDiscovery completed:")
    print(f"  Sources processed: {stats['sources_processed']}")
    print(f"  Candidates found: {stats['total_candidates_discovered']}")
    print(f"  Success rate: {stats['sources_succeeded']}/{stats['sources_processed']}")
