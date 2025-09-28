"""Database-driven URL discovery using newspaper4k and storysniffer.

This module integrates with the existing pipeline by:
1. Reading publisher URLs from the sources table
2. Using newspaper4k for RSS feed discovery and parsing
3. Using storysniffer for intelligent article URL detection
4. Storing discovered candidate URLs in the candidate_links table

Designed for SQLite with future Postgres migration in mind.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from sqlalchemy import text
import feedparser  # type: ignore[import]
from .scheduling import parse_frequency_to_days
from newspaper import Config, build  # type: ignore[import]
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
    _parse_date = None

from ..models.database import DatabaseManager, upsert_candidate_link
from src.utils.telemetry import (
    OperationType,
    OperationMetrics,
    DiscoveryMethod,
    DiscoveryMethodStatus,
    create_telemetry_system,
)
from src.utils.discovery_outcomes import DiscoveryOutcome, DiscoveryResult

logger = logging.getLogger(__name__)


def _newspaper_build_worker(
    target_url: str,
    out_path: str,
    fetch_images_flag: bool,
):
    """Worker function executed in a separate process to perform
    `newspaper.build` and write discovered article URLs to `out_path`.

    Implemented at module-level so it's picklable on platforms using the
    'spawn' start method (macOS).
    """
    try:
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
        database_url: str = "sqlite:///data/mizzou.db",
        user_agent: Optional[str] = None,
        timeout: int = 30,
        delay: float = 2.0,
        max_articles_per_source: int = 50,
        days_back: int = 7,
    ):
        """Initialize the discovery system.

        Args:
            database_url: Database connection string
            user_agent: User agent string for requests
            timeout: Request timeout in seconds
            delay: Delay between requests in seconds
            max_articles_per_source: Maximum candidate URLs per source
            days_back: How many days back to look for articles
        """
        self.database_url = database_url
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
        self.telemetry = create_telemetry_system(
            database_url=self.database_url,
        )

        logger.info(f"NewsDiscovery initialized with {days_back}-day window")
        logger.info(
            "Articles published before "
            f"{self.cutoff_date.strftime('%Y-%m-%d')} will be filtered out"
        )

        self._known_hosts_cache: Set[str] | None = None

    @staticmethod
    def _normalize_host(host: Optional[str]) -> Optional[str]:
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

    def _iter_host_candidates(self, value: Any) -> List[str]:
        hosts: List[str] = []
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
        source_meta: Optional[dict],
    ) -> Set[str]:
        hosts: Set[str] = set()

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

    def _update_source_meta(
        self,
        source_id: Optional[str],
        updates: Dict[str, Any],
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
                res = conn.execute(
                    text("SELECT metadata FROM sources WHERE id = :id"),
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

                conn.execute(
                    text(
                        "UPDATE sources SET metadata = :meta WHERE id = :id"
                    ),
                    {"meta": json.dumps(merged), "id": source_id},
                )
        except Exception:
            logger.debug(
                "Failed to update metadata for source %s",
                source_id,
            )

    def _reset_rss_failure_state(
        self,
        source_id: Optional[str],
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
        source_id: Optional[str],
    ) -> None:
        if not source_id:
            return
        try:
            dbm = DatabaseManager(self.database_url)
            with dbm.engine.connect() as conn:
                query = text(
                    "SELECT metadata FROM sources WHERE id = :id"
                )
                result = conn.execute(
                    query,
                    {"id": source_id},
                ).fetchone()

            cur_meta: Dict[str, Any] = {}
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
                updates["rss_missing"] = (
                    datetime.utcnow().isoformat()
                )

            self._update_source_meta(source_id, updates)
        except Exception:
            missing_iso = datetime.utcnow().isoformat()
            self._update_source_meta(
                source_id,
                {"rss_missing": missing_iso},
            )

    def _get_existing_urls(self) -> Set[str]:
        """Return existing URLs from candidate_links to avoid duplicates."""
        try:
            db_manager = DatabaseManager(self.database_url)

            with db_manager.engine.connect() as conn:
                result = conn.execute(text("SELECT url FROM candidate_links"))
                return {row[0] for row in result.fetchall()}

        except Exception as e:
            logger.warning(f"Could not fetch existing URLs: {e}")
            return set()

    @staticmethod
    def _rss_retry_window_days(freq: Optional[str]) -> int:
        """Return the number of days before retrying RSS after a miss.

        We interpret the declared publishing frequency into a conservative
        cooldown and cap it so that we always retry within a week. Missing
        or malformed frequencies fall back to a 7-day window.
        """

        try:
            days = parse_frequency_to_days(freq)
        except Exception:
            return 7

        return max(1, min(7, days * 2))

    def _is_recent_article(self, publish_date: Optional[datetime]) -> bool:
        """Check if article was published within the date window."""
        if not publish_date:
            return True  # Include articles without dates (benefit of doubt)

        return publish_date >= self.cutoff_date

    def _get_existing_urls_for_source(self, source_id: str) -> Set[str]:
        """Get existing URLs for a source to detect duplicates."""
        try:
            db_manager = DatabaseManager(self.database_url)
            with db_manager.engine.connect() as conn:
                result = conn.execute(
                    text(
                        "SELECT url FROM candidate_links "
                        "WHERE source_host_id = :source_id"
                    ),
                    {"source_id": source_id},
                )
                return {row[0] for row in result.fetchall()}
        except Exception:
            logger.debug(f"Failed to get existing URLs for source {source_id}")
            return set()

    def _get_existing_article_count(self, source_id: str) -> int:
        """Count already-extracted articles for a source."""
        try:
            db_manager = DatabaseManager(self.database_url)
            with db_manager.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT COUNT(a.id)
                        FROM articles a
                        JOIN candidate_links cl ON a.candidate_link_id = cl.id
                        WHERE cl.source_id = :source_id
                        """
                    ),
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

    def get_sources_to_process(
        self,
        dataset_label: Optional[str] = None,
        limit: Optional[int] = None,
        due_only: bool = True,
        host_filter: Optional[str] = None,
        city_filter: Optional[str] = None,
        county_filter: Optional[str] = None,
        host_limit: Optional[int] = None,
    ) -> tuple[pd.DataFrame, Dict[str, int]]:
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
            # Use actual schema: id, host, host_norm, canonical_name,
            # city, county, owner, type, metadata
            # Prioritize sources that have never been attempted for discovery
            where_clauses = ["s.host IS NOT NULL", "s.host != ''"]
            params: Dict[str, Any] = {}

            join_clause = ""
            if dataset_label:
                join_clause = (
                    "\nJOIN dataset_sources ds ON s.id = ds.source_id"
                    "\nJOIN datasets d ON ds.dataset_id = d.id"
                )
                where_clauses.append("d.label = :dataset_label")
                params["dataset_label"] = dataset_label

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

            query = f"""
            SELECT DISTINCT
                s.id,
                s.canonical_name as name,
                'https://' || s.host as url,
                s.metadata,
                s.city,
                s.county,
                s.type as type_classification,
                s.host,
                CASE
                    WHEN cl.source_host_id IS NULL THEN 0
                    ELSE 1
                END as discovery_attempted
            FROM sources s
            LEFT JOIN candidate_links cl ON s.id = cl.source_host_id
            {join_clause}
            WHERE {where_sql}
            ORDER BY discovery_attempted ASC, s.canonical_name ASC
            """

            if limit:
                try:
                    safe_limit = int(limit)
                    if safe_limit > 0:
                        query += f" LIMIT {safe_limit}"
                except Exception:
                    pass

            df = pd.read_sql_query(query, db.engine, params=params or None)

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
                            row.get("metadata")
                            if "metadata" in row.index else None
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
                    except Exception:
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
        source_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        source_meta: Optional[dict] = None,
        allow_build: bool = True,
        rss_already_attempted: bool = False,
    ) -> List[Dict]:
        """Use newspaper4k to discover articles from a news source.

        OPTIMIZED VERSION: Focus on RSS discovery first; fallback to HTML

            Args:
                source_url: The base URL of the news source

            Returns:
                List of discovered article metadata
        """
        discovered_articles = []
        method_start_time = time.time()
        homepage_status_code: Optional[int] = None

        def record_newspaper_effectiveness(
            status: DiscoveryMethodStatus,
            articles_found: int,
            *,
            status_codes: Optional[List[int]] = None,
            notes: Optional[str] = None,
        ) -> None:
            if not (
                self.telemetry
                and source_id
                and operation_id
            ):
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
                resp = self.session.get(
                    source_url, timeout=min(5, self.timeout)
                )
                homepage_status_code = getattr(resp, "status_code", None)
                homepage_fetch_ms = (
                    (time.time() - homepage_request_start) * 1000
                )
                html = resp.text or ""
                # Look for <link ... type="application/rss+xml" href="..."> or
                # atom
                import re

                # If rss_missing is set in the source metadata, or if the
                # caller already attempted RSS discovery for this source in
                # this run, skip probing for feed <link> tags to avoid
                # duplicate feed fetches.
                skip_internal_feed_probe = False
                try:
                    if source_meta and isinstance(source_meta, dict):
                        if source_meta.get("rss_missing"):
                            skip_internal_feed_probe = True
                except Exception:
                    skip_internal_feed_probe = False

                # If the caller already tried RSS feeds, avoid re-trying
                if rss_already_attempted:
                    skip_internal_feed_probe = True

                if not skip_internal_feed_probe:
                    rss_type = (
                        r"(?:application/rss\+xml|application/atom\+xml)"
                    )
                    pattern = (
                        r'<link[^>]+type=["\']' + rss_type + r'["\'][^>]*'
                        r"href=[\"']([^\"']+)[\"']"
                    )
                    matches = re.findall(pattern, html, flags=re.I)
                    if matches:
                        feeds = [urljoin(source_url, m) for m in matches]
                        logger.info(
                            (
                                "Found %d feed(s) on homepage; "
                                "trying those first"
                            ) % (len(feeds),)
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
                                ) % (len(rss_results),)
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
                # Quick link-scan fallback: extract anchor hrefs from the
                # homepage and look for article-like paths. This is much
                # cheaper than running `newspaper.build` for sites that do
                # not have RSS feeds.
                try:
                    import re

                    hrefs = re.findall(
                        r'href=["\']([^"\']+)["\']', html, flags=re.I
                    )
                    candidates = []
                    parsed_base = urlparse(source_url)
                    for h in hrefs:
                        # Normalize and skip mailto/tele/JS
                        if (
                            h.startswith("mailto:")
                            or h.startswith("tel:")
                            or h.startswith("javascript:")
                        ):
                            continue
                        full = urljoin(source_url, h)
                        p = urlparse(full)
                        # Only same-host links
                        if p.netloc != parsed_base.netloc:
                            continue
                        # Heuristic: path contains keywords indicating articles
                        path = p.path.lower()
                        # If source has an active rss_missing flag, avoid
                        # treating feed-like URLs as candidates to prevent
                        # downstream feed fetch attempts (e.g. '/feed',
                        # '/rss').
                        if source_meta and isinstance(source_meta, dict):
                            try:
                                if source_meta.get("rss_missing") and (
                                    "feed" in path or "rss" in path
                                ):
                                    continue
                            except Exception:
                                pass
                        if any(
                            k in path
                            for k in (
                                "/news",
                                "/article",
                                "/stories",
                                "/story",
                                "/post",
                                "/202",
                                "/20",
                            )
                        ):
                            candidates.append(full)
                    # Deduplicate and limit
                    unique = []
                    seen = set()
                    for u in candidates:
                        if u in seen:
                            continue
                        seen.add(u)
                        unique.append(u)
                        if len(unique) >= min(
                            self.max_articles_per_source, 25
                        ):
                            break
                    if unique:
                        logger.info(
                            "Homepage link-scan found %d candidate URLs; "
                            "returning those instead of building",
                            len(unique),
                        )
                        # Convert to discovery records
                        existing_urls = self._get_existing_urls()
                        out = []
                        discovered_at = datetime.utcnow().isoformat()
                        for u in unique:
                            if u in existing_urls:
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
                            existing_urls.add(u)
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
                    pass
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
                    from multiprocessing import Process
                    import tempfile
                    import os

                    tmpf = tempfile.NamedTemporaryFile(delete=False)
                    tmp_path = tmpf.name
                    tmpf.close()

                    fetch_images_flag = False
                    try:
                        # config may omit fetch_images; default to False
                        fetch_images_flag = bool(
                            getattr(config, "fetch_images", False)
                        )
                    except Exception:
                        fetch_images_flag = False

                    proc = Process(
                        target=_newspaper_build_worker,
                        args=(source_url, tmp_path, fetch_images_flag),
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
                            self.articles = [
                                _FakeArticle(u) for u in (urls or [])
                            ]

                    paper = _FakePaper(urls)

                except Exception as e:
                    logger.warning(
                        f"newspaper4k build raised for {source_url}: {e}"
                    )

            # Don't download all articles - just get the URLs
            articles_attr = []
            if paper is not None:
                articles_attr = getattr(paper, "articles", []) or []
            article_count = len(articles_attr)
            logger.info("Found %d potential articles" % (article_count,))

            if article_count == 0:
                logger.warning(
                    "No articles found via newspaper4k for %s", source_url
                )
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
            articles_to_process = articles_attr[
                : min(self.max_articles_per_source, 25)
            ]

            for article in articles_to_process:
                try:
                    # Skip if URL already exists
                    if article.url in existing_urls:
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
                    existing_urls.add(article.url)  # Track newly added URLs

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
                    [homepage_status_code]
                    if homepage_status_code is not None
                    else None
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

    def _format_discovered_by(self, article_data: Dict) -> str:
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
        source_id: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> List[Dict]:
        """Use storysniffer to intelligently detect article URLs.

        Args:
            source_url: The base URL of the news source

        Returns:
            List of discovered article metadata
        """
        discovered_articles = []
        method_start_time = time.time()

        def record_storysniffer_effectiveness(
            status: DiscoveryMethodStatus,
            articles_found: int,
            *,
            notes: Optional[str] = None,
        ) -> None:
            if not (
                self.telemetry
                and source_id
                and operation_id
            ):
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

        try:
            logger.info(f"Using storysniffer for: {source_url}")

            # Use storysniffer to detect article URLs
            results = self.storysniffer.guess(source_url)

            # StorySniffer.guess() returns a list of URLs
            for item in results if isinstance(results, list) else []:
                # item may be a URL string or a dict with metadata
                if isinstance(item, str):
                    url = item
                    meta = {}
                elif isinstance(item, dict):
                    url = item.get("url")
                    meta = item
                else:
                    continue

                article_data = {
                    "url": url,
                    "source_url": source_url,
                    "discovery_method": "storysniffer",
                    "discovered_at": datetime.utcnow().isoformat(),
                    "confidence_score": 1.0,
                    "metadata": {
                        "storysniffer_data": meta,
                        "detection_method": "ml_prediction",
                    },
                }

                if isinstance(meta, dict) and meta.get("title"):
                    article_data["title"] = meta.get("title")
                if isinstance(meta, dict) and meta.get("publish_date"):
                    article_data["publish_date"] = meta.get("publish_date")

                discovered_articles.append(article_data)

            article_count = len(discovered_articles)
            logger.info(f"StorySniffer found {article_count} articles")
            status = (
                DiscoveryMethodStatus.SUCCESS
                if article_count > 0
                else DiscoveryMethodStatus.NO_FEED
            )
            notes = None
            if article_count == 0:
                notes = "storysniffer returned 0 candidates"
            record_storysniffer_effectiveness(
                status,
                article_count,
                notes=notes,
            )

        except Exception as e:
            msg = "Failed to discover articles with storysniffer"
            logger.error(f"{msg} for {source_url}: {e}")
            record_storysniffer_effectiveness(
                DiscoveryMethodStatus.SERVER_ERROR,
                len(discovered_articles),
                notes=str(e)[:200],
            )

        return discovered_articles

    def discover_with_rss_feeds(
        self,
        source_url: str,
        source_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        custom_rss_feeds: Optional[List[str]] = None,
        source_meta: Optional[dict] = None,
    ) -> Tuple[List[Dict], Dict]:
        """Attempt to discover RSS feeds and extract article URLs - OPTIMIZED.

        Args:
            source_url: Base URL of the news source.
            custom_rss_feeds: Optional list of known RSS feed URLs
                for this source.

        Returns:
            List of discovered article metadata from RSS feeds
        """
        discovered_articles = []
        start_time = time.time()
        feeds_tried = 0
        feeds_successful = 0
        duplicate_count = 0
        old_article_count = 0
        network_error_count = 0

        # Build candidate feed list (custom first, then common paths)
        potential_feeds: List[str] = []
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
                            error_message=(
                                "Timeout after %ds" % (self.timeout,)
                            ),
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
                    logger.warning(
                        "Connection error for RSS feed: %s", feed_url
                    )
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
                            content_length=len(
                                getattr(response, "content", b"")
                            ),
                        )
                    except Exception:
                        pass

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
                        if article_url in existing_urls:
                            duplicate_count += 1
                            continue

                        publish_date = None
                        if entry.get("published_parsed"):
                            try:
                                publish_date = datetime(
                                    *entry.published_parsed[:6]
                                )
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
                            article_data["publish_date"] = (
                                publish_date.isoformat()
                            )

                        discovered_articles.append(article_data)
                        existing_urls.add(article_url)

                    # Fallback: if feed had entries but all filtered out,
                    # optionally include a small recent set
                    if (
                        len(discovered_articles) == start_len
                        and entry_count > 0
                    ):
                        recent_activity_days = 90
                        try:
                            freq = None
                            if source_meta and isinstance(source_meta, dict):
                                freq = (
                                    source_meta.get("frequency")
                                    or source_meta.get("freq")
                                )
                            if freq:
                                parsed = parse_frequency_to_days(freq)
                                recent_activity_days = max(1, parsed * 3)
                        except Exception:
                            recent_activity_days = 90

                        most_recent = None
                        try:
                            if getattr(feed, "feed", None) and feed.feed.get(
                                "updated_parsed"
                            ):
                                most_recent = datetime(
                                    *feed.feed.updated_parsed[:6]
                                )
                            for e in feed.entries:
                                if e.get("published_parsed"):
                                    try:
                                        d = datetime(*e.published_parsed[:6])
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
                            fallback_count = min(
                                5, self.max_articles_per_source
                            )
                            for entry in feed.entries[:fallback_count]:
                                article_url = entry.get("link")
                                if (
                                    not article_url
                                    or article_url in existing_urls
                                ):
                                    continue
                                    continue
                                article_data = {
                                    "url": article_url,
                                    "source_url": source_url,
                                    "discovery_method": "rss_feed",
                                    "discovered_at": (
                                        datetime.utcnow().isoformat()
                                    ),
                                    "title": (
                                        (entry.get("title") or "").strip()
                                    ),
                                    "metadata": {
                                        "rss_feed_url": feed_url,
                                        "feed_entry_count": entry_count,
                                        "fallback_include_older": True,
                                    },
                                }
                                if entry.get("published_parsed"):
                                    try:
                                        pd = datetime(
                                            *entry.published_parsed[:6]
                                        )
                                        article_data[
                                            "publish_date"
                                        ] = pd.isoformat()
                                    except Exception:
                                        pass
                                discovered_articles.append(article_data)
                                existing_urls.add(article_url)

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
                        "Tried %d feeds, %d successful" % (
                            feeds_tried, feeds_successful
                        )
                    ),
                )
            except Exception:
                pass

        summary = {
            "feeds_tried": feeds_tried,
            "feeds_successful": feeds_successful,
            "network_errors": network_error_count,
        }

        return discovered_articles, summary

    def process_source(
        self,
        source_row: pd.Series,
        dataset_label: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> DiscoveryResult:
        """Process a single source and store discovered URLs.

        Args:
            source_row: Pandas Series containing source information
            dataset_label: Dataset label for the candidate links
            operation_id: Operation ID for telemetry tracking

        Returns:
            DiscoveryResult with detailed outcome information
        """
        source_url = str(source_row["url"])
        source_name = str(source_row["name"])
        source_id = str(source_row["id"])

        logger.info(f"Processing source: {source_name} ({source_url})")

        # Track discovery results for detailed outcome reporting
        articles_found_total = 0
        articles_new = 0
        articles_duplicate = 0
        articles_expired = 0
        discovery_methods_attempted = []

        all_discovered = []
        start_time = time.time()

        # Get existing URLs to check for duplicates
        existing_urls = self._get_existing_urls_for_source(source_id)

        # Get effective discovery methods for this source
        effective_methods = []
        if self.telemetry:
            effective_methods = self.telemetry.get_effective_discovery_methods(
                source_id
            )
            if effective_methods:
                logger.info(
                    f"Using effective methods for {source_name}: "
                    f"{[method.value for method in effective_methods]}"
                )

        # If the source metadata records a last successful method, prefer it
        # for the next discovery run (try it first). We allow a string value
        # stored in sources.metadata['last_successful_method'] such as
        # 'rss_feed', 'newspaper4k', or 'storysniffer'. Map that to the
        # corresponding DiscoveryMethod and move it to the front of the
        # effective_methods list if present.
        try:
            raw_meta = None
            if "metadata" in source_row.index:
                raw_meta = source_row.get("metadata")
                if raw_meta and isinstance(raw_meta, str):
                    try:
                        raw_meta = json.loads(raw_meta)
                    except Exception:
                        raw_meta = None
            if raw_meta and isinstance(raw_meta, dict):
                last_success = raw_meta.get("last_successful_method")
                if last_success and isinstance(last_success, str):
                    key = last_success.strip().lower()
                    mapping = {
                        "rss_feed": DiscoveryMethod.RSS_FEED,
                        "rss": DiscoveryMethod.RSS_FEED,
                        "newspaper4k": DiscoveryMethod.NEWSPAPER4K,
                        "newspaper": DiscoveryMethod.NEWSPAPER4K,
                        "storysniffer": DiscoveryMethod.STORYSNIFFER,
                        "story_sniffer": DiscoveryMethod.STORYSNIFFER,
                    }
                    preferred = mapping.get(key)
                    if preferred:
                        # Ensure effective_methods is a list of DiscoveryMethod
                        if not effective_methods:
                            effective_methods = [preferred]
                        else:
                            # Move preferred to front if present, else insert
                            try:
                                if preferred in effective_methods:
                                    effective_methods.remove(preferred)
                                effective_methods.insert(0, preferred)
                            except Exception:
                                # Best-effort only
                                pass
                        logger.info(
                            "Prioritizing last successful method for %s: %s",
                            source_name,
                            preferred.value,
                        )
        except Exception:
            # Non-fatal — continue with telemetry-provided ordering
            pass

        # Prepare a parsed `source_meta` for use by all discovery methods.
        source_meta = None
        try:
            if "metadata" in source_row.index:
                raw_meta_val = source_row.get("metadata")
                if raw_meta_val and isinstance(raw_meta_val, str):
                    source_meta = json.loads(raw_meta_val)
                elif raw_meta_val and isinstance(raw_meta_val, dict):
                    source_meta = raw_meta_val
        except Exception:
            source_meta = None

        allowed_hosts = self._collect_allowed_hosts(source_row, source_meta)

        # Whether to skip probing RSS feeds based on recent metadata; set a
        # default here so downstream logic always has the variable.
        skip_rss = False

        # If no historical data, use all methods
        if not effective_methods:
            effective_methods = [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
                DiscoveryMethod.STORYSNIFFER,
            ]
            logger.info("No historical data for %s", source_name)
            logger.info("Trying all methods")

        # Try multiple discovery methods in order of effectiveness/speed
        try:
            # Track whether RSS discovery was attempted in this run so we
            # don't cause `discover_with_newspaper4k` to probe feeds again
            # for the same source.
            rss_attempted = False
            # Method 1: RSS feeds (fastest and most reliable)
            if DiscoveryMethod.RSS_FEED in effective_methods:
                try:
                    # Extract custom RSS feeds if available
                    custom_rss_feeds = None
                    if (
                        hasattr(source_row, "rss_feeds")
                        and source_row.rss_feeds
                    ):
                        if isinstance(source_row.rss_feeds, str):
                            try:
                                custom_rss_feeds = json.loads(
                                    source_row.rss_feeds
                                )
                            except (json.JSONDecodeError, TypeError):
                                custom_rss_feeds = [source_row.rss_feeds]
                        elif isinstance(source_row.rss_feeds, list):
                            custom_rss_feeds = source_row.rss_feeds

                    # Reuse parsed source metadata for RSS heuristics.
                    source_meta_local = source_meta

                    # Determine if we should skip RSS. If the source was
                    # previously marked missing, we may avoid probing feeds.
                    skip_rss = False
                    try:
                        rss_missing_ts = None
                        if (
                            source_meta_local
                            and isinstance(source_meta_local, dict)
                        ):
                            rss_missing_ts = source_meta_local.get(
                                "rss_missing"
                            )

                        if rss_missing_ts:
                            try:
                                # Parse timestamp (assume ISO format)
                                missing_dt = datetime.fromisoformat(
                                    rss_missing_ts
                                )
                            except Exception:
                                missing_dt = None

                            # Compute recency window based on declared
                            # frequency. We try a shorter cooldown so that
                            # sources marked as missing because of temporary
                            # feed issues recover within a couple of cycles.
                            recent_activity_days = 90
                            try:
                                freq = (
                                    source_meta_local.get("frequency")
                                    if source_meta_local
                                    else None
                                )
                                if freq:
                                    # Allow re-attempt after roughly two
                                    # cadence periods, capped at one week.
                                    recent_activity_days = (
                                        self._rss_retry_window_days(freq)
                                    )
                            except Exception:
                                recent_activity_days = 90

                            if missing_dt:
                                threshold = datetime.utcnow() - timedelta(
                                    days=recent_activity_days
                                )
                                if missing_dt >= threshold:
                                    skip_rss = True
                                    logger.info(
                                        "Skipping RSS for %s because "
                                        "rss_missing set on %s",
                                        source_name,
                                        missing_dt.isoformat(),
                                    )
                    except Exception:
                        skip_rss = False

                    if skip_rss:
                        logger.info(
                            "Skipping RSS discovery for %s due to a recent "
                            "rss_missing flag",
                            source_name,
                        )
                        rss_articles = []
                    else:
                        try:
                            rss_attempted = True
                            discovery_methods_attempted.append("rss_feed")
                            _rss_ret = self.discover_with_rss_feeds(
                                source_url,
                                source_id,
                                operation_id,
                                custom_rss_feeds,
                                source_meta=source_meta,
                            )
                            # Backwards compatibility: allow monkeypatched
                            # functions to return either a list (old behavior)
                            # or (list, summary).
                            if (
                                isinstance(_rss_ret, tuple)
                                and len(_rss_ret) == 2
                            ):
                                rss_articles, rss_summary = _rss_ret
                            else:
                                rss_articles = _rss_ret or []
                                rss_summary = {
                                    "feeds_tried": int(bool(rss_articles)),
                                    "feeds_successful": int(
                                        bool(rss_articles)
                                    ),
                                    "network_errors": 0,
                                }
                            all_discovered.extend(rss_articles)
                            logger.info(
                                "RSS discovery found %d articles",
                                len(rss_articles),
                            )

                            # Persist metadata about discovery method
                            # effectiveness
                            try:
                                if rss_articles and source_id:
                                    # Successful discovery: clear all failure
                                    # counters/flags
                                    self._update_source_meta(
                                        source_id,
                                        {
                                            "last_successful_method": (
                                                "rss_feed"
                                            ),
                                            "rss_missing": None,
                                            "rss_last_failed": None,
                                            "rss_consecutive_failures": 0,
                                        },
                                    )
                                elif source_id and not rss_articles:
                                    # We attempted feeds but found no articles.
                                    feeds_tried = rss_summary.get(
                                        "feeds_tried", 0
                                    )
                                    feeds_successful = rss_summary.get(
                                        "feeds_successful", 0
                                    )
                                    network_errors = rss_summary.get(
                                        "network_errors", 0
                                    )

                                    if (
                                        feeds_tried > 0
                                        and feeds_successful == 0
                                    ):
                                        if network_errors > 0:
                                            # Transient network failures: reset
                                            # counters without marking missing.
                                            self._reset_rss_failure_state(
                                                source_id,
                                            )
                                        else:
                                            # Non-network failure (e.g. 404 or
                                            # parse). Increment counters and
                                            # mark missing once threshold hits.
                                            self._increment_rss_failure(
                                                source_id,
                                            )
                            except Exception:
                                logger.debug(
                                    (
                                        "Failed to persist RSS discovery "
                                        "metadata for source %s"
                                    ),
                                    source_id,
                                )

                        except Exception as rss_error:
                            logger.warning(
                                "RSS discovery failed for %s: %s",
                                source_name,
                                rss_error,
                            )
                            # Record specific RSS failure
                            if operation_id:
                                try:
                                    self.telemetry.record_site_failure(
                                        operation_id=operation_id,
                                        site_url=source_url,
                                        error=rss_error,
                                        site_name=source_name,
                                        discovery_method="rss",
                                        response_time_ms=(
                                            time.time() - start_time
                                        )
                                        * 1000,
                                    )
                                except Exception:
                                    pass

                            # Decide whether this looks like a transient
                            # network error.
                            is_network_error = False
                            try:
                                import requests as _requests

                                if isinstance(
                                    rss_error,
                                    (
                                        _requests.exceptions.Timeout,
                                        _requests.exceptions.ConnectionError,
                                    ),
                                ):
                                    is_network_error = True
                            except Exception:
                                # Fallback to message inspection
                                msg = str(rss_error).lower()
                                if (
                                    "timeout" in msg
                                    or "timed out" in msg
                                    or "connection" in msg
                                ):
                                    is_network_error = True

                            try:
                                if source_id:
                                    if is_network_error:
                                        # Transient issue: record last failed
                                        # timestamp but avoid marking missing.
                                        failed_iso = (
                                            datetime.utcnow().isoformat()
                                        )
                                        self._update_source_meta(
                                            source_id,
                                            {"rss_last_failed": failed_iso},
                                        )
                                    else:
                                        # Treat as permanent failure to
                                        # find RSS (parse/404).
                                        missing_iso = (
                                            datetime.utcnow().isoformat()
                                        )
                                        self._update_source_meta(
                                            source_id,
                                            {"rss_missing": missing_iso},
                                        )
                            except Exception:
                                logger.debug(
                                    "Failed to persist rss failure for %s",
                                    source_id,
                                )
                except Exception as rss_error:
                    logger.warning(
                        "RSS discovery failed for %s: %s",
                        source_name,
                        rss_error,
                    )
                    # Record specific RSS failure
                    if operation_id:
                        self.telemetry.record_site_failure(
                            operation_id=operation_id,
                            site_url=source_url,
                            error=rss_error,
                            site_name=source_name,
                            discovery_method="rss",
                            response_time_ms=(time.time() - start_time) * 1000,
                        )
            else:
                logger.info(
                    "Skipping RSS discovery for %s (historically ineffective)",
                    source_name,
                )

            # If RSS found enough articles, skip slower methods
            if len(all_discovered) >= self.max_articles_per_source // 2:
                logger.info(
                    "RSS found sufficient articles, skipping slower methods"
                )
            else:
                # Method 2: newspaper4k (slower but comprehensive)
                if DiscoveryMethod.NEWSPAPER4K in effective_methods:
                    try:
                        discovery_methods_attempted.append("newspaper4k")
                        newspaper_articles = self.discover_with_newspaper4k(
                            source_url,
                            source_id,
                            operation_id,
                            source_meta=source_meta,
                            allow_build=(not skip_rss),
                            rss_already_attempted=rss_attempted,
                        )
                        all_discovered.extend(newspaper_articles)
                        logger.info(
                            "newspaper4k found %d articles",
                            len(newspaper_articles),
                        )
                    except Exception as newspaper_error:
                        logger.warning(
                            f"newspaper4k discovery failed for {source_name}: "
                            f"{newspaper_error}"
                        )
                        # Record specific newspaper4k failure
                        if operation_id:
                            self.telemetry.record_site_failure(
                                operation_id=operation_id,
                                site_url=source_url,
                                error=newspaper_error,
                                site_name=source_name,
                                discovery_method="newspaper4k",
                                response_time_ms=(
                                    time.time() - start_time
                                )
                                * 1000,
                            )
                else:
                    logger.info(
                        f"Skipping newspaper4k for {source_name} "
                        f"(historically ineffective)"
                    )

                # Method 3: storysniffer (if available and still need more)
                if (
                    self.storysniffer
                    and len(all_discovered) < self.max_articles_per_source
                ):
                    try:
                        discovery_methods_attempted.append("storysniffer")
                        storysniffer_articles = (
                            self.discover_with_storysniffer(
                                source_url,
                                source_id,
                                operation_id,
                            )
                        )
                        all_discovered.extend(storysniffer_articles)
                        logger.info(
                            "storysniffer found %d articles",
                            len(storysniffer_articles),
                        )
                    except Exception as storysniffer_error:
                        logger.warning(
                            "storysniffer discovery failed for %s: %s",
                            source_name,
                            storysniffer_error,
                        )
                        # Record specific storysniffer failure
                        if operation_id:
                            self.telemetry.record_site_failure(
                                operation_id=operation_id,
                                site_url=source_url,
                                error=storysniffer_error,
                                site_name=source_name,
                                discovery_method="storysniffer",
                                response_time_ms=(
                                    time.time() - start_time
                                )
                                * 1000,
                            )

        except Exception as e:
            logger.error(f"Error during discovery for {source_name}: {e}")
            # Record overall site failure
            if operation_id:
                self.telemetry.record_site_failure(
                    operation_id=operation_id,
                    site_url=source_url,
                    error=e,
                    site_name=source_name,
                    discovery_method="multiple",
                    response_time_ms=(time.time() - start_time) * 1000,
                )
            return DiscoveryResult(
                outcome=DiscoveryOutcome.UNKNOWN_ERROR,
                error_details=str(e),
                metadata={"source_name": source_name,
                          "error_location": "discovery_pipeline"}
            )

        # If no articles found, record as content error
        if len(all_discovered) == 0:
            if operation_id:
                content_error = Exception(
                    "No articles discovered from any method")
                self.telemetry.record_site_failure(
                    operation_id=operation_id,
                    site_url=source_url,
                    error=content_error,
                    site_name=source_name,
                    discovery_method="all_methods",
                    response_time_ms=(
                        time.time() - start_time
                    )
                    * 1000,
                )

        # Categorize discovered articles
        articles_found_total = len(all_discovered)

        # Deduplicate by URL and categorize
        unique_articles = {}
        for article in all_discovered:
            url = article.get("url")
            if url and url not in unique_articles:
                unique_articles[url] = article

        logger.info(f"Total unique articles found: {len(unique_articles)}")

        # Categorize articles by type
        articles_new = 0
        articles_duplicate = 0
        articles_expired = 0
        articles_out_of_scope = 0
        stored_count = 0

        # Store in database and track outcomes
        with DatabaseManager(self.database_url) as db:
            for raw_url, article_data in unique_articles.items():
                candidate_url = article_data.get("url") or raw_url
                url = candidate_url
                try:
                    parsed = urlparse(candidate_url)
                    if not parsed.netloc:
                        absolute_url = urljoin(source_url, candidate_url)
                        parsed = urlparse(absolute_url)
                    else:
                        absolute_url = candidate_url

                    host_value = parsed.netloc
                    normalized_host = self._normalize_host(host_value)

                    if (
                        allowed_hosts
                        and (
                            not normalized_host
                            or normalized_host not in allowed_hosts
                        )
                    ):
                        articles_out_of_scope += 1
                        logger.debug(
                            "Skipping out-of-scope URL %s for %s",
                            absolute_url,
                            source_name,
                        )
                        continue

                    if not host_value:
                        articles_out_of_scope += 1
                        logger.debug(
                            "Skipping URL without host %s for %s",
                            candidate_url,
                            source_name,
                        )
                        continue

                    url = absolute_url

                    # Check if this URL already exists
                    if url in existing_urls:
                        articles_duplicate += 1
                        continue

                    # Check if article is within date range
                    discovered_publish_date = article_data.get("publish_date")
                    if discovered_publish_date:
                        try:
                            if isinstance(discovered_publish_date, datetime):
                                typed_publish_date = discovered_publish_date
                            else:
                                typed_publish_date = datetime.fromisoformat(
                                    discovered_publish_date
                                )

                            if not self._is_recent_article(typed_publish_date):
                                articles_expired += 1
                                continue
                        except Exception:
                            # If we can't parse date, treat as valid
                            pass

                    # This is a new, valid article scoped to the source
                    articles_new += 1

                    # Build a descriptive discovered_by label using helper
                    discovered_by_label = None
                    try:
                        discovered_by_label = (
                            self._format_discovered_by(article_data)
                        )
                    except Exception:
                        discovered_by_label = (
                            "discovery_pipeline_"
                            + str(
                                article_data.get(
                                    "discovery_method", "unknown"
                                )
                            )
                        )

                    # Convert publish date for storage
                    typed_publish_date = None
                    if discovered_publish_date:
                        try:
                            if isinstance(discovered_publish_date, datetime):
                                typed_publish_date = discovered_publish_date
                            else:
                                try:
                                    fromiso = datetime.fromisoformat
                                    typed_publish_date = fromiso(
                                        discovered_publish_date
                                    )
                                except Exception:
                                    if _parse_date:
                                        typed_publish_date = _parse_date(
                                            discovered_publish_date
                                        )
                                    else:
                                        raise
                        except Exception:
                            logger.debug(
                                (
                                    "Unable to parse discovered publish_date "
                                    "'%s' for %s"
                                ),
                                discovered_publish_date,
                                url,
                            )

                    candidate_data = {
                        "url": url,
                        "source": source_name,
                        "source_id": source_id,
                        "source_host_id": source_id,  # Sets source_host_id
                        "dataset_id": dataset_label,
                        "discovered_by": discovered_by_label,
                        "publish_date": typed_publish_date,
                        "meta": {
                            **(article_data.get("metadata", {}) or {}),
                            **(
                                {"publish_date": discovered_publish_date}
                                if discovered_publish_date
                                else {}
                            ),
                        },
                        "status": "discovered",
                        "priority": 1,
                        "source_name": source_name,
                        "source_city": source_row.get("city"),
                        "source_county": source_row.get("county"),
                        "source_type": source_row.get("type_classification"),
                    }

                    # Use the existing upsert function
                    upsert_candidate_link(db.session, **candidate_data)
                    stored_count += 1
                    existing_urls.add(url)

                except Exception as e:
                    logger.error(
                        "Failed to store candidate URL %s: %s",
                        candidate_url,
                        e,
                    )
                    continue

        logger.info(f"Stored {stored_count} candidate URLs for {source_name}")

        # Determine primary outcome
        if articles_new > 0:
            outcome = DiscoveryOutcome.NEW_ARTICLES_FOUND
        elif articles_duplicate > 0 and articles_expired > 0:
            outcome = DiscoveryOutcome.MIXED_RESULTS
        elif articles_duplicate > 0:
            outcome = DiscoveryOutcome.DUPLICATES_ONLY
        elif articles_expired > 0:
            outcome = DiscoveryOutcome.EXPIRED_ONLY
        elif articles_found_total == 0:
            outcome = DiscoveryOutcome.NO_ARTICLES_FOUND
        else:
            outcome = DiscoveryOutcome.UNKNOWN_ERROR

        return DiscoveryResult(
            outcome=outcome,
            articles_found=articles_found_total,
            articles_new=articles_new,
            articles_duplicate=articles_duplicate,
            articles_expired=articles_expired,
            method_used=(
                ",".join(discovery_methods_attempted)
                if discovery_methods_attempted
                else "unknown"
            ),
            metadata={
                "source_name": source_name,
                "discovery_time_ms": (time.time() - start_time) * 1000,
                "methods_attempted": discovery_methods_attempted,
                "stored_count": stored_count,
                "out_of_scope_skipped": articles_out_of_scope,
            }
        )

    def run_discovery(
        self,
        dataset_label: Optional[str] = None,
        source_limit: Optional[int] = None,
        source_filter: Optional[str] = None,
        source_uuids: Optional[List[str]] = None,
        due_only: bool = False,
        host_filter: Optional[str] = None,
        city_filter: Optional[str] = None,
        county_filter: Optional[str] = None,
        host_limit: Optional[int] = None,
        existing_article_limit: Optional[int] = None,
    ) -> Dict[str, int]:
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
                mask = (
                    sources_df["name"].str.contains(
                        source_filter,
                        case=False,
                        na=False,
                    )
                    | sources_df["url"].str.contains(
                        source_filter,
                        case=False,
                        na=False,
                    )
                )
                sources_df = sources_df[mask]

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
                if (
                    existing_article_limit is not None
                    and existing_article_limit >= 0
                ):
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
                        source_name=str(
                            source_row.get("name", "Unknown")
                        ),
                        source_url=str(source_row.get("url", "")),
                        discovery_result=discovery_result,
                    )

                    stats["sources_processed"] += 1
                    stats["total_candidates_discovered"] += (
                        discovery_result.articles_new
                    )

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

                    logger.info(
                        f"Progress: {stats['sources_processed']}/"
                        f"{len(sources_df)} sources"
                    )

                    # Respectful delay between sources
                    time.sleep(self.delay)

                    # Persist a last discovery timestamp into source
                    # metadata. Scheduling logic can use this when
                    # candidate_links haven't yet been updated or when
                    # processed_at is not present.
                    try:
                        self._update_source_meta(
                            source_row.get("id"),
                            {
                                "last_discovery_at":
                                datetime.utcnow().isoformat(),
                            },
                        )
                    except Exception:
                        # Don't let metadata write failures interrupt discovery
                        logger.debug(
                            "Failed to persist last_discovery_at for %s",
                            source_row.get("id"),
                        )

                except Exception as e:
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
                        message=(
                            "Failed: "
                            f"{source_row.get('name', 'Unknown')}"
                        ),
                    )

            logger.info(
                "Discovery complete. Processed %s sources, found %s "
                "candidate URLs",
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

        result = db_manager.session.execute(query).fetchall()
        return [
            {
                "id": row[0],
                "host": row[1],
                "canonical_name": row[2],
                "url": f"https://{row[1]}",
            }
            for row in result
        ]

    except Exception as e:
        logger.error(f"Error querying sources: {e}")
        return []


def run_discovery_pipeline(
    dataset_label: Optional[str] = None,
    source_limit: Optional[int] = None,
    source_filter: Optional[str] = None,
    source_uuids: Optional[List[str]] = None,
    database_url: str = "sqlite:///data/mizzou.db",
    max_articles_per_source: int = 50,
    days_back: int = 7,
    host_filter: Optional[str] = None,
    city_filter: Optional[str] = None,
    county_filter: Optional[str] = None,
    host_limit: Optional[int] = None,
    existing_article_limit: Optional[int] = None,
) -> Dict[str, int]:
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
    print(
        "  Success rate: "
        f"{stats['sources_succeeded']}/{stats['sources_processed']}"
    )
