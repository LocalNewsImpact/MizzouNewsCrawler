from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

from src.utils.discovery_outcomes import DiscoveryOutcome, DiscoveryResult
from src.utils.telemetry import DiscoveryMethod

logger = logging.getLogger(__name__)


@dataclass
class SourceProcessor:
    """Coordinated processor for the discovery pipeline per source."""

    discovery: Any
    source_row: pd.Series
    dataset_label: str | None = None
    operation_id: str | None = None
    date_parser: Any | None = None

    source_url: str = field(init=False)
    source_name: str = field(init=False)
    source_id: str = field(init=False)
    dataset_id: str | None = field(init=False)  # Resolved UUID from dataset_label
    start_time: float = field(init=False)
    existing_urls: set[str] = field(init=False)
    source_meta: dict | None = field(init=False)
    allowed_hosts: set[str] = field(init=False)
    effective_methods: list[DiscoveryMethod] = field(init=False)
    discovery_methods_attempted: list[str] = field(init=False)
    rss_summary: dict[str, int] = field(default_factory=dict, init=False)

    def process(self) -> DiscoveryResult:
        self._initialize_context()
        try:
            all_discovered = self._run_discovery_methods()
        except Exception as exc:  # pragma: no cover - defensive
            return self._handle_global_failure(exc)

        if not all_discovered:
            self._record_no_articles()

        stats = self._store_candidates(all_discovered)
        return self._build_result(all_discovered, stats)

    # ------------------------------------------------------------------
    # Context setup helpers
    # ------------------------------------------------------------------
    def _initialize_context(self) -> None:
        self.source_url = str(self.source_row["url"])
        self.source_name = str(self.source_row["name"])
        self.source_id = str(self.source_row["id"])
        self.start_time = time.time()

        # Resolve dataset_label to UUID for consistent database storage
        self.dataset_id = self._resolve_dataset_label()

        logger.info(
            "Processing source: %s (%s)",
            self.source_name,
            self.source_url,
        )

        if self.dataset_id:
            logger.debug(
                "Resolved dataset '%s' to UUID: %s",
                self.dataset_label,
                self.dataset_id,
            )

        self.existing_urls = self.discovery._get_existing_urls_for_source(
            self.source_id
        )
        self.source_meta = self._parse_source_meta()
        self.allowed_hosts = self.discovery._collect_allowed_hosts(
            self.source_row,
            self.source_meta,
        )

        self.discovery_methods_attempted = []
        self.effective_methods = self._determine_effective_methods()

    def _parse_source_meta(self) -> dict | None:
        if "metadata" not in self.source_row.index:
            return None
        raw_meta = self.source_row.get("metadata")
        if not raw_meta:
            return None
        if isinstance(raw_meta, dict):
            return raw_meta
        if isinstance(raw_meta, str):
            try:
                return json.loads(raw_meta)
            except Exception:
                return None
        return None

    def _resolve_dataset_label(self) -> str | None:
        """Resolve dataset_label (name/slug) to canonical UUID.

        Returns:
            Dataset UUID as string, or None if no dataset specified
        """
        if not self.dataset_label:
            return None

        try:
            from src.utils.dataset_utils import resolve_dataset_id

            # Get database engine from discovery object
            db_manager = self.discovery._create_db_manager()
            dataset_uuid = resolve_dataset_id(db_manager.engine, self.dataset_label)
            return dataset_uuid
        except ValueError as e:
            # Log the error but don't fail the entire discovery process
            logger.error(
                "Failed to resolve dataset '%s': %s",
                self.dataset_label,
                str(e),
            )
            # Return None to continue without dataset tagging
            return None
        except Exception as e:
            logger.warning(
                "Unexpected error resolving dataset '%s': %s",
                self.dataset_label,
                str(e),
            )
            return None

    def _determine_effective_methods(self) -> list[DiscoveryMethod]:
        # Check if source is already paused due to repeated failures
        if self.source_meta:
            failure_count = self.source_meta.get("no_effective_methods_consecutive", 0)
            if failure_count >= 3:
                logger.warning(
                    "Skipping discovery for %s: already at failure threshold (%d/3)",
                    self.source_name,
                    failure_count,
                )
                return []

        telemetry = getattr(self.discovery, "telemetry", None)
        methods: list[DiscoveryMethod] = []
        has_historical_data = False

        if telemetry:
            try:
                has_historical_data = telemetry.has_historical_data(self.source_id)
                methods = (
                    telemetry.get_effective_discovery_methods(self.source_id) or []
                )
            except Exception:
                methods = []

        if methods:
            logger.info(
                "Using effective methods for %s: %s",
                self.source_name,
                [method.value for method in methods],
            )

        methods = self._prioritize_last_success(methods)

        if not methods:
            if has_historical_data:
                logger.info(
                    "No effective methods found for %s, trying all methods",
                    self.source_name,
                )
            else:
                logger.info(
                    "No historical data for %s, trying all methods",
                    self.source_name,
                )
            # Note: STORYSNIFFER removed from default methods as it's a URL
            # classifier (not a discovery crawler) and cannot discover articles
            # from homepages without additional HTML parsing logic.
            return [
                DiscoveryMethod.RSS_FEED,
                DiscoveryMethod.NEWSPAPER4K,
            ]
        return methods

    def _prioritize_last_success(
        self,
        methods: list[DiscoveryMethod],
    ) -> list[DiscoveryMethod]:
        if not isinstance(self.source_meta, dict):
            return list(methods)
        last_success = self.source_meta.get("last_successful_method")
        if not isinstance(last_success, str):
            return list(methods)

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
        if not preferred:
            return list(methods)

        ordered = list(methods) if methods else []
        if preferred in ordered:
            ordered.remove(preferred)
        ordered.insert(0, preferred)
        logger.info(
            "Prioritizing last successful method for %s: %s",
            self.source_name,
            preferred.value,
        )
        return ordered

    # ------------------------------------------------------------------
    # Discovery method orchestration
    # ------------------------------------------------------------------
    def _run_discovery_methods(self) -> list[dict[str, Any]]:
        all_discovered: list[dict[str, Any]] = []
        rss_attempted = False
        skip_rss = False

        if DiscoveryMethod.RSS_FEED in self.effective_methods:
            (
                rss_articles,
                rss_summary,
                rss_attempted,
                skip_rss,
            ) = self._try_rss()
            self.rss_summary = rss_summary
            all_discovered.extend(rss_articles)
        else:
            logger.info(
                "Skipping RSS discovery for %s (historically ineffective)",
                self.source_name,
            )

        # If RSS found a healthy volume, skip slower methods.
        if len(all_discovered) >= self.discovery.max_articles_per_source // 2:
            logger.info(
                "RSS found sufficient articles, skipping slower methods",
            )
            return all_discovered

        # Method 2: newspaper4k
        if DiscoveryMethod.NEWSPAPER4K in self.effective_methods:
            newspaper_articles = self._try_newspaper(skip_rss, rss_attempted)
            all_discovered.extend(newspaper_articles)
        else:
            logger.info(
                "Skipping newspaper4k for %s (historically ineffective)",
                self.source_name,
            )

        # Method 3: storysniffer
        # Note: StorySniffer is a URL classifier (returns boolean), not a
        # discovery crawler. It cannot discover article URLs from homepages.
        # Skip it for discovery entirely.
        if DiscoveryMethod.STORYSNIFFER in self.effective_methods:
            logger.debug(
                "StorySniffer in effective methods but cannot discover URLs "
                "from homepages (it's a classifier, not a crawler). Skipping."
            )
        # Legacy code path kept for reference but effectively disabled
        # as discover_with_storysniffer now returns empty list immediately

        return all_discovered

    def _extract_custom_rss_feeds(self) -> list[str] | None:
        if not hasattr(self.source_row, "rss_feeds"):
            return None
        feeds = self.source_row.rss_feeds
        if not feeds:
            return None
        if isinstance(feeds, str):
            try:
                parsed = json.loads(feeds)
                if isinstance(parsed, list):
                    return parsed
                return [feeds]
            except (json.JSONDecodeError, TypeError):
                return [feeds]
        if isinstance(feeds, list):
            return feeds
        return None

    def _should_skip_rss(self) -> bool:
        meta = self.source_meta
        if not isinstance(meta, dict):
            return False
        rss_missing_ts = meta.get("rss_missing")
        if not rss_missing_ts:
            return False
        try:
            missing_dt = datetime.fromisoformat(rss_missing_ts)
        except Exception:
            return False

        try:
            freq = meta.get("frequency") if meta else None
            recent_activity_days = self.discovery._rss_retry_window_days(freq)
        except Exception:
            recent_activity_days = 90

        threshold = datetime.utcnow() - timedelta(days=recent_activity_days)
        if missing_dt >= threshold:
            logger.info(
                "Skipping RSS for %s because rss_missing set on %s",
                self.source_name,
                missing_dt.isoformat(),
            )
            return True
        return False

    def _try_rss(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, int], bool, bool]:
        articles: list[dict[str, Any]] = []
        summary = {
            "feeds_tried": 0,
            "feeds_successful": 0,
            "network_errors": 0,
        }
        attempted = False
        skip_rss = False

        custom_rss_feeds = self._extract_custom_rss_feeds()
        if self._should_skip_rss():
            logger.info(
                "Skipping RSS discovery for %s due to recent rss_missing",
                self.source_name,
            )
            skip_rss = True
            return articles, summary, attempted, skip_rss

        rss_meta = self.source_meta if isinstance(self.source_meta, dict) else None

        try:
            attempted = True
            self.discovery_methods_attempted.append("rss_feed")
            rss_result = self.discovery.discover_with_rss_feeds(
                self.source_url,
                self.source_id,
                self.operation_id,
                custom_rss_feeds,
                source_meta=rss_meta,
            )
            if isinstance(rss_result, tuple) and len(rss_result) == 2:
                articles, summary = rss_result
            else:
                articles = rss_result or []
                summary = {
                    "feeds_tried": int(bool(articles)),
                    "feeds_successful": int(bool(articles)),
                    "network_errors": 0,
                }

            self._persist_rss_metadata(articles, summary)
        except Exception as rss_error:  # pragma: no cover - side effects
            self._handle_rss_failure(rss_error)
        return articles, summary, attempted, skip_rss

    def _persist_rss_metadata(
        self,
        articles: list[dict[str, Any]],
        summary: dict[str, int],
    ) -> None:
        if not self.source_id:
            return
        try:
            feeds_tried = summary.get("feeds_tried", 0)
            feeds_successful = summary.get("feeds_successful", 0)
            network_errors = summary.get("network_errors", 0)
            if articles:
                self.discovery._update_source_meta(
                    self.source_id,
                    {
                        "last_successful_method": "rss_feed",
                        "rss_missing": None,
                        "rss_last_failed": None,
                        "rss_consecutive_failures": 0,
                    },
                )
            elif feeds_tried > 0 and feeds_successful == 0:
                if network_errors > 0:
                    self.discovery._reset_rss_failure_state(self.source_id)
                else:
                    self.discovery._increment_rss_failure(self.source_id)
        except Exception:
            logger.debug(
                "Failed to persist RSS discovery metadata for source %s",
                self.source_id,
            )

    def _handle_rss_failure(self, rss_error: Exception) -> None:
        logger.warning(
            "RSS discovery failed for %s: %s",
            self.source_name,
            rss_error,
        )
        telemetry = getattr(self.discovery, "telemetry", None)
        if telemetry and self.operation_id:
            try:
                telemetry.record_site_failure(
                    operation_id=self.operation_id,
                    site_url=self.source_url,
                    error=rss_error,
                    site_name=self.source_name,
                    discovery_method="rss",
                    response_time_ms=(time.time() - self.start_time) * 1000,
                )
            except Exception as e:
                logger.debug(
                    "Failed to record RSS failure telemetry for %s: %s",
                    self.source_name,
                    str(e),
                )

        is_network_error = False
        try:
            if isinstance(
                rss_error,
                (
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                ),
            ):
                is_network_error = True
        except Exception:
            msg = str(rss_error).lower()
            if "timeout" in msg or "timed out" in msg or "connection" in msg:
                is_network_error = True

        try:
            if not self.source_id:
                return
            if is_network_error:
                failed_iso = datetime.utcnow().isoformat()
                self.discovery._update_source_meta(
                    self.source_id,
                    {"rss_last_failed": failed_iso},
                )
            else:
                missing_iso = datetime.utcnow().isoformat()
                self.discovery._update_source_meta(
                    self.source_id,
                    {"rss_missing": missing_iso},
                )
        except Exception:
            logger.debug(
                "Failed to persist rss failure for %s",
                self.source_id,
            )

    def _try_newspaper(
        self,
        skip_rss: bool,
        rss_attempted: bool,
    ) -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        try:
            self.discovery_methods_attempted.append("newspaper4k")
            articles = self.discovery.discover_with_newspaper4k(
                self.source_url,
                self.source_id,
                self.operation_id,
                source_meta=self.source_meta,
                allow_build=(not skip_rss),
                rss_already_attempted=rss_attempted,
            )
            logger.info(
                "newspaper4k found %d articles",
                len(articles),
            )
        except Exception as newspaper_error:  # pragma: no cover - telemetry
            logger.warning(
                "newspaper4k discovery failed for %s: %s",
                self.source_name,
                newspaper_error,
            )
            telemetry = getattr(self.discovery, "telemetry", None)
            if telemetry and self.operation_id:
                try:
                    telemetry.record_site_failure(
                        operation_id=self.operation_id,
                        site_url=self.source_url,
                        error=newspaper_error,
                        site_name=self.source_name,
                        discovery_method="newspaper4k",
                        response_time_ms=(time.time() - self.start_time) * 1000,
                    )
                except Exception:
                    pass
        return articles or []

    def _try_storysniffer(self) -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        if not getattr(self.discovery, "storysniffer", None):
            return articles
        try:
            self.discovery_methods_attempted.append("storysniffer")
            articles = self.discovery.discover_with_storysniffer(
                self.source_url,
                self.source_id,
                self.operation_id,
            )
            logger.info(
                "storysniffer found %d articles",
                len(articles),
            )
        except Exception as story_error:  # pragma: no cover - telemetry
            logger.warning(
                "storysniffer discovery failed for %s: %s",
                self.source_name,
                story_error,
            )
            telemetry = getattr(self.discovery, "telemetry", None)
            if telemetry and self.operation_id:
                try:
                    telemetry.record_site_failure(
                        operation_id=self.operation_id,
                        site_url=self.source_url,
                        error=story_error,
                        site_name=self.source_name,
                        discovery_method="storysniffer",
                        response_time_ms=(time.time() - self.start_time) * 1000,
                    )
                except Exception:
                    pass
        return articles or []

    # ------------------------------------------------------------------
    # Storage and classification helpers
    # ------------------------------------------------------------------
    def _store_candidates(
        self,
        all_discovered: list[dict[str, Any]],
    ) -> dict[str, int]:
        articles_found_total = len(all_discovered)
        unique_articles: dict[str, dict[str, Any]] = {}
        for article in all_discovered:
            url = article.get("url")
            if not url:
                continue
            normalized_url = self.discovery._normalize_candidate_url(url)
            if normalized_url not in unique_articles:
                unique_articles[normalized_url] = article

        logger.info(
            "Total unique articles found: %d",
            len(unique_articles),
        )

        articles_new = 0
        articles_duplicate = 0
        articles_expired = 0
        articles_out_of_scope = 0
        stored_count = 0

        with self.discovery._create_db_manager() as db:
            for raw_url, article_data in unique_articles.items():
                candidate_url = article_data.get("url") or raw_url
                url = candidate_url
                try:
                    parsed = urlparse(candidate_url)
                    if not parsed.netloc:
                        absolute_url = urljoin(self.source_url, candidate_url)
                        parsed = urlparse(absolute_url)
                    else:
                        absolute_url = candidate_url

                    host_value = parsed.netloc
                    normalized_host = self.discovery._normalize_host(
                        host_value,
                    )

                    if self.allowed_hosts and (
                        not normalized_host or normalized_host not in self.allowed_hosts
                    ):
                        articles_out_of_scope += 1
                        logger.debug(
                            "Skipping out-of-scope URL %s for %s",
                            absolute_url,
                            self.source_name,
                        )
                        continue

                    if not host_value:
                        articles_out_of_scope += 1
                        logger.debug(
                            "Skipping URL without host %s for %s",
                            candidate_url,
                            self.source_name,
                        )
                        continue

                    url = absolute_url

                    normalized_candidate = self.discovery._normalize_candidate_url(url)

                    if normalized_candidate in self.existing_urls:
                        articles_duplicate += 1
                        continue

                    discovered_publish_date = article_data.get("publish_date")
                    if discovered_publish_date:
                        try:
                            typed_publish_date = self._coerce_publish_date(
                                discovered_publish_date
                            )
                            if (
                                typed_publish_date
                                and not self.discovery._is_recent_article(  # noqa: E501
                                    typed_publish_date
                                )
                            ):
                                articles_expired += 1
                                continue
                        except Exception:
                            typed_publish_date = None
                    else:
                        typed_publish_date = None

                    articles_new += 1
                    discovered_by_label = self._format_discovered_by(article_data)

                    candidate_data = {
                        "url": url,
                        "source": self.source_name,
                        "source_id": self.source_id,
                        "source_host_id": self.source_id,
                        # Use resolved UUID instead of label
                        "dataset_id": self.dataset_id,
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
                        "source_name": self.source_name,
                        "source_city": self.source_row.get("city"),
                        "source_county": self.source_row.get("county"),
                        "source_type": self.source_row.get("type_classification"),
                    }

                    from ..models.database import upsert_candidate_link  # lazy

                    upsert_candidate_link(db.session, **candidate_data)
                    stored_count += 1
                    self.existing_urls.add(normalized_candidate)

                except Exception as exc:  # pragma: no cover - logging
                    logger.error(
                        "Failed to store candidate URL %s: %s",
                        candidate_url,
                        exc,
                    )
                    continue

        # Reset 'no effective methods' counter if we successfully stored articles
        if stored_count > 0:
            self.discovery._reset_no_effective_methods(self.source_id)

        return {
            "articles_found_total": articles_found_total,
            "articles_new": articles_new,
            "articles_duplicate": articles_duplicate,
            "articles_expired": articles_expired,
            "articles_out_of_scope": articles_out_of_scope,
            "stored_count": stored_count,
        }

    def _coerce_publish_date(
        self,
        value: Any,
    ) -> datetime | None:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except Exception:
            if self.date_parser:
                try:
                    parsed = self.date_parser(value)
                    if isinstance(parsed, datetime):
                        return parsed
                except Exception:
                    return None
        return None

    def _format_discovered_by(self, article_data: dict[str, Any]) -> str:
        try:
            return self.discovery._format_discovered_by(article_data)
        except Exception:
            method = article_data.get("discovery_method", "unknown")
            return f"discovery_pipeline_{method}"

    # ------------------------------------------------------------------
    # Result + telemetry helpers
    # ------------------------------------------------------------------
    def _record_no_articles(self) -> None:
        telemetry = getattr(self.discovery, "telemetry", None)
        if telemetry and self.operation_id:
            content_error = Exception("No articles discovered from any method")
            try:
                telemetry.record_site_failure(
                    operation_id=self.operation_id,
                    site_url=self.source_url,
                    error=content_error,
                    site_name=self.source_name,
                    discovery_method="all_methods",
                    response_time_ms=(time.time() - self.start_time) * 1000,
                )
            except Exception:
                pass

        # Check if this source has historical data and captures
        has_historical_data = False
        if telemetry:
            try:
                has_historical_data = telemetry.has_historical_data(self.source_id)
            except Exception:
                pass

        # Only track "no effective methods" failures for sources with:
        # 1. No historical data (new/struggling sources)
        # 2. Zero article captures ever
        if not has_historical_data:
            article_count = self.discovery._get_existing_article_count(self.source_id)
            if article_count == 0:
                # Increment consecutive failure counter
                failure_count = self.discovery._increment_no_effective_methods(
                    self.source_id
                )
                logger.warning(
                    "No effective methods and zero articles captured from %s "
                    "(failure count: %d/3)",
                    self.source_name,
                    failure_count,
                )

                # Pause after 3 consecutive failures
                if failure_count >= 3:
                    self.discovery._pause_source(
                        self.source_id,
                        (
                            "Automatic pause after 3 consecutive 'no effective "
                            "methods' attempts"
                        ),
                        host=self.source_name,
                    )
                    logger.warning(
                        "Source %s paused after %d consecutive failures "
                        "with no captures",
                        self.source_name,
                        failure_count,
                    )

    def _handle_global_failure(self, exc: Exception) -> DiscoveryResult:
        logger.error(
            "Error during discovery for %s: %s",
            self.source_name,
            exc,
        )
        telemetry = getattr(self.discovery, "telemetry", None)
        if telemetry and self.operation_id:
            try:
                telemetry.record_site_failure(
                    operation_id=self.operation_id,
                    site_url=self.source_url,
                    error=exc,
                    site_name=self.source_name,
                    discovery_method="multiple",
                    response_time_ms=(time.time() - self.start_time) * 1000,
                )
            except Exception:
                pass
        return DiscoveryResult(
            outcome=DiscoveryOutcome.UNKNOWN_ERROR,
            error_details=str(exc),
            metadata={
                "source_name": self.source_name,
                "error_location": "discovery_pipeline",
            },
        )

    def _build_result(
        self,
        all_discovered: list[dict[str, Any]],
        stats: dict[str, int],
    ) -> DiscoveryResult:
        outcome = self._determine_outcome(stats)
        return DiscoveryResult(
            outcome=outcome,
            articles_found=stats["articles_found_total"],
            articles_new=stats["articles_new"],
            articles_duplicate=stats["articles_duplicate"],
            articles_expired=stats["articles_expired"],
            method_used=(
                ",".join(self.discovery_methods_attempted)
                if self.discovery_methods_attempted
                else "unknown"
            ),
            metadata={
                "source_name": self.source_name,
                "discovery_time_ms": (time.time() - self.start_time) * 1000,
                "methods_attempted": self.discovery_methods_attempted,
                "stored_count": stats["stored_count"],
                "out_of_scope_skipped": stats["articles_out_of_scope"],
            },
        )

    def _determine_outcome(self, stats: dict[str, int]) -> DiscoveryOutcome:
        if stats["articles_new"] > 0:
            return DiscoveryOutcome.NEW_ARTICLES_FOUND
        if stats["articles_duplicate"] > 0 and stats["articles_expired"] > 0:
            return DiscoveryOutcome.MIXED_RESULTS
        if stats["articles_duplicate"] > 0:
            return DiscoveryOutcome.DUPLICATES_ONLY
        if stats["articles_expired"] > 0:
            return DiscoveryOutcome.EXPIRED_ONLY
        if stats["articles_found_total"] == 0:
            return DiscoveryOutcome.NO_ARTICLES_FOUND
        return DiscoveryOutcome.UNKNOWN_ERROR
