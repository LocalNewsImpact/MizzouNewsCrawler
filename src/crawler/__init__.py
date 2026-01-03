# ruff: noqa

"""News crawler module for discovering and fetching articles."""

import hashlib
import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime
from html import unescape
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Set, Tuple, cast
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from dateutil import parser as dateparser

from src.utils.bot_sensitivity_manager import BotSensitivityManager
from src.utils.comprehensive_telemetry import ExtractionMetrics

from .fingerprint_profile import (
    FingerprintProfile,
    load_fingerprint_profile,
    prepare_user_data_dir,
)
from .proxy_config import ProxyProvider, get_proxy_manager
from .utils import mask_proxy_url

UNBLOCK_MIN_HTML_BYTES = 3000

_SELENIUM_DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]


class RateLimitError(Exception):
    """Exception raised when a domain is rate limited."""

    pass


class NotFoundError(Exception):
    """Exception raised when a URL returns 404/410 (permanent missing)."""

    pass


class ProxyChallengeError(Exception):
    """Exception raised when proxy returns a challenge/block page.

    Indicates anti-bot protection that requires cooldown and retry.
    Should NOT trigger fallback to other extraction methods.
    """

    pass


# Enhanced extraction dependencies
try:
    from newspaper import Article as NewspaperArticle

    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False
    logging.warning("newspaper4k not available, falling back to BeautifulSoup only")

# MediaCloud metadata extractor
mcmetadata: ModuleType | None
MCMETADATA_AVAILABLE = False
try:
    import mcmetadata as mcmetadata_module

    mcmetadata = mcmetadata_module
    MCMETADATA_AVAILABLE = True
except ImportError:
    mcmetadata = None
    try:
        src_root = Path(__file__).resolve().parents[1]
        src_str = os.fspath(src_root)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)

        import mcmetadata as mcmetadata_module

        mcmetadata = mcmetadata_module
        MCMETADATA_AVAILABLE = True
    except ImportError:
        logging.warning("mcmetadata not available, mcmetadata extraction disabled")

# Cloudscraper for Cloudflare bypass
try:
    import cloudscraper

    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    cloudscraper = None
    logging.warning("cloudscraper not available, Cloudflare bypass disabled")

# Selenium imports with advanced anti-detection
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    logging.warning("Selenium not available, final fallback disabled")

# Advanced anti-detection libraries
try:
    import undetected_chromedriver as uc

    UNDETECTED_CHROME_AVAILABLE = True
except ImportError:
    UNDETECTED_CHROME_AVAILABLE = False
    logging.warning("undetected-chromedriver not available, using standard Selenium")

try:
    from selenium_stealth import stealth

    SELENIUM_STEALTH_AVAILABLE = True
except ImportError:
    SELENIUM_STEALTH_AVAILABLE = False
    logging.warning("selenium-stealth not available, using basic stealth mode")

logger = logging.getLogger(__name__)


_HEARST_SOURCE_ASSIGNMENT_RE = re.compile(
    r"window\.HRST\.article\.sourceName\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_HEARST_SOURCE_JSON_BLOCK_RE = re.compile(
    r"window\.HRST\.article\s*=\s*({.*?})\s*;",
    re.IGNORECASE | re.DOTALL,
)
_HEARST_SOURCE_VALUE_RE = re.compile(r'"sourceName"\s*:\s*"([^\"]+)"', re.IGNORECASE)

# Gannett/USA Today JSON-LD patterns
_GANNETT_JSONLD_BLOCK_RE = re.compile(
    r'<script\s+type\s*=\s*["\']?application/ld\+json["\']?\s*>([^<]+)</script>',
    re.IGNORECASE | re.DOTALL,
)
_GANNETT_WIRE_PUBLISHERS = {
    "usa today",
    "usatoday",
}

# Generic structured metadata patterns for wire detection
# These are CMS-agnostic patterns that appear across many publishers

# OpenGraph-style distributor meta tags (e.g., Gray TV stations)
# <meta property="article:distributor_category" content="wires"/>
# <meta property="article:distributor_name" content="AP National"/>
_META_DISTRIBUTOR_CATEGORY_RE = re.compile(
    r'<meta\s+[^>]*property\s*=\s*["\']article:distributor_category["\'][^>]*'
    r'content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_DISTRIBUTOR_NAME_RE = re.compile(
    r'<meta\s+[^>]*property\s*=\s*["\']article:distributor_name["\'][^>]*'
    r'content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Alternate order: content before property
_META_DISTRIBUTOR_CATEGORY_ALT_RE = re.compile(
    r'<meta\s+[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*'
    r'property\s*=\s*["\']article:distributor_category["\']',
    re.IGNORECASE,
)
_META_DISTRIBUTOR_NAME_ALT_RE = re.compile(
    r'<meta\s+[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*'
    r'property\s*=\s*["\']article:distributor_name["\']',
    re.IGNORECASE,
)

# Canonical URL extraction
_CANONICAL_LINK_RE = re.compile(
    r'<link\s+[^>]*rel\s*=\s*["\']canonical["\'][^>]*href\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_CANONICAL_LINK_ALT_RE = re.compile(
    r'<link\s+[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*rel\s*=\s*["\']canonical["\']',
    re.IGNORECASE,
)

# Meta author tag (can contain wire service names with suffix patterns)
# E.g., <meta name="author" content="Hanna Park, Betsy Klein, CNN"/>
_META_AUTHOR_RE = re.compile(
    r'<meta\s+[^>]*name\s*=\s*["\']author["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_AUTHOR_ALT_RE = re.compile(
    r'<meta\s+[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*name\s*=\s*["\']author["\']',
    re.IGNORECASE,
)

# CMS dataLayer syndication fields (TownNews, others)
# tncms.syndication.source, tncms.syndication.origin, townnews.content.source
_DATALAYER_SYNDICATION_SOURCE_RE = re.compile(
    r'["\']?(?:tncms\.syndication\.source|townnews\.content\.source)["\']?\s*'
    r'[=:]\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_DATALAYER_SYNDICATION_ORIGIN_RE = re.compile(
    r'["\']?tncms\.syndication\.origin["\']?\s*[=:]\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_DATALAYER_SYNDICATION_CHANNEL_RE = re.compile(
    r'["\']?tncms\.syndication\.channel["\']?\s*[=:]\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Known wire service domains for canonical URL cross-reference
_WIRE_SERVICE_DOMAINS = {
    "apnews.com": "The Associated Press",
    "ap.org": "The Associated Press",
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
    "afp.com": "Agence France-Presse",
    "usatoday.com": "USA Today",
    "cnn.com": "CNN",
    "foxnews.com": "Fox News",
    "nbcnews.com": "NBC News",
    "abcnews.go.com": "ABC News",
    "cbsnews.com": "CBS News",
    "healthday.com": "HealthDay",
    "upi.com": "UPI",
    "npr.org": "NPR",
    "pbs.org": "PBS",
    "washingtonpost.com": "Washington Post",
    "nytimes.com": "New York Times",
    "latimes.com": "Los Angeles Times",
}

# CMS-specific JavaScript data object patterns for content metadata extraction
# These capture title, author, and other fields from CMS JavaScript objects

# Nexstar Media (NXSTdata.content) - used by many TV stations
# window.NXSTdata.content = Object.assign(window.NXSTdata.content, {...})
_NXST_CONTENT_RE = re.compile(
    r"window\.NXSTdata\.content\s*=\s*Object\.assign\s*\(\s*"
    r"window\.NXSTdata\.content\s*,\s*(\{[^}]+\})\s*\)",
    re.IGNORECASE | re.DOTALL,
)

# Generic window.__DATA__ or window.pageData patterns
_WINDOW_DATA_RE = re.compile(
    r"window\.__(?:INITIAL_)?DATA__\s*=\s*(\{.*?\});?\s*(?:</script>|$)",
    re.IGNORECASE | re.DOTALL,
)

# Gray Television dataLayer.push pattern
_GRAY_DATALAYER_RE = re.compile(
    r'dataLayer\.push\s*\(\s*(\{[^}]*"articleTitle"[^}]*\})\s*\)',
    re.IGNORECASE | re.DOTALL,
)


def _ensure_attrs_dict(attrs: object) -> dict:
    """Coerce BeautifulSoup `attrs` argument into a dict suitable for
    `soup.find(selector, attrs=...)`.

    BeautifulSoup allows attribute values to be a dict, a list, or other
    types. This helper returns a dict when possible and falls back to an
    empty dict otherwise.
    """
    if isinstance(attrs, dict):
        return attrs
    # Handle typical BeautifulSoup shapes: list/tuple of (k,v) pairs
    if isinstance(attrs, (list, tuple)):
        try:
            return {k: v for k, v in attrs}  # type: ignore[misc]
        except Exception:
            return {}
    # Unknown shape -> empty dict
    return {}


URL_DATE_FALLBACK_HOSTS = {
    "columbiatribune.com",
    "kbia.org",
    "unterrifieddemocrat.com",
    "mexicoledger.com",
}


URL_DATE_REGEX_PATTERNS = [
    (
        "slash_year_month_day",
        r"/(?P<year>20\d{2})/(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/|$)",
    ),
    (
        "dash_year_month_day",
        r"(?<!\d)(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)",
    ),
    (
        "underscore_year_month_day",
        r"(?<!\d)(?P<year>20\d{2})_(?P<month>\d{1,2})_(?P<day>\d{1,2})(?!\d)",
    ),
    (
        "compact_year_month_day",
        r"/(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?:/|$)",
    ),
]

PUBLISH_DATE_KEYWORD_REGEX = re.compile(
    r"\b(?P<keyword>published|posted|updated|last\s+updated|modified|"
    r"date\s+published|first\s+published)\b",
    re.IGNORECASE,
)

MAX_TEXT_BLOCK_LENGTH = 240

DATE_ONLY_REGEX_PATTERNS = [
    re.compile(
        r"^(?:"  # Optional day of week prefix
        r"(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|"
        r"Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)[,\s]+)?"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?:\.)?\s+"
        r"\d{1,2}(?:st|nd|rd|th)?(?:,)?\s+20\d{2}"
        r"(?:\s+\d{1,2}:\d{2}(?:\s*[ap]m)?)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^20\d{2}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$",
    ),
    re.compile(
        r"^\d{1,2}/\d{1,2}/20\d{2}(?:\s+\d{1,2}:\d{2}(?:\s*[ap]m)?)?$",
    ),
]


class NewsCrawler:
    """Main crawler class for discovering and fetching news articles."""

    def __init__(self, user_agent: str = None, timeout: int = 20, delay: float = 1.0):
        # Use a realistic default User-Agent instead of identifying as a crawler
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        )
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and properly formatted."""
        try:
            parsed = urlparse(url)
            # Only allow http and https schemes for crawling
            if not parsed.scheme or not parsed.netloc:
                return False
            return parsed.scheme.lower() in ("http", "https")
        except Exception:
            return False

    def discover_links(self, seed_url: str) -> Tuple[Set[str], Set[str]]:
        """Discover internal and external links from a seed URL.

        Returns:
            Tuple of (internal_urls, external_urls)
        """
        domain_name = urlparse(seed_url).netloc
        internal_urls = set()
        external_urls = set()

        try:
            logger.info(f"Discovering links from: {seed_url}")
            resp = self.session.get(seed_url, timeout=self.timeout)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.content, "html.parser")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href")
                if not href:
                    continue

                # BeautifulSoup `attrs` may be a list/tuple; normalize to a string
                if isinstance(href, (list, tuple)):
                    href = href[0] if href else ""
                href = str(href)

                # Resolve relative URLs
                href = urljoin(seed_url, href)
                parsed_href = urlparse(href)

                # Normalize URL (remove fragment, query params
                # for deduplication)
                normalized_url = (
                    f"{parsed_href.scheme}://{parsed_href.netloc}{parsed_href.path}"
                )

                if not self.is_valid_url(normalized_url):
                    continue

                if domain_name in parsed_href.netloc:
                    internal_urls.add(normalized_url)
                else:
                    external_urls.add(normalized_url)

            logger.info(
                f"Found {len(internal_urls)} internal, "
                f"{len(external_urls)} external links"
            )

        except Exception as e:
            logger.error(f"Error discovering links from {seed_url}: {e}")

        # Add delay between requests
        time.sleep(self.delay)

        return internal_urls, external_urls

    def fetch_page(self, url: str) -> Optional[str]:
        """Fetch HTML content from a URL.

        Returns:
            Raw HTML content or None if fetch failed
        """
        try:
            logger.debug(f"Fetching: {url}")
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()

            # Add delay between requests
            time.sleep(self.delay)

            return resp.text

        except Exception as e:
            logger.warning(f"Error fetching {url}: {e}")
            return None

    def filter_article_urls(
        self, urls: Set[str], site_rules: Dict[str, Any] = None
    ) -> List[str]:
        """Filter URLs to identify likely article pages.

        Args:
            urls: Set of URLs to filter
            site_rules: Site-specific filtering rules

        Returns:
            List of URLs that appear to be articles
        """
        article_urls = []

        for url in urls:
            if self._is_likely_article(url, site_rules):
                article_urls.append(url)

        logger.info(
            f"Filtered {len(urls)} URLs to {len(article_urls)} article candidates"
        )
        return sorted(article_urls)

    def _is_likely_article(self, url: str, site_rules: Dict[str, Any] = None) -> bool:
        """Determine if a URL is likely an article page."""
        # Default filters - skip known non-article paths
        skip_patterns = [
            "/show",
            "/podcast",
            "/category",
            "/tag",
            "/author",
            "/page/",
            "/search",
            "/login",
            "/register",
            "/contact",
            "/about",
            "/privacy",
            "/terms",
            "/sitemap",
            "/posterboard-ads/",
            "/classifieds/",
            "/marketplace/",
            "/deals/",
            "/coupons/",
            "/promotions/",
            "/sponsored/",
        ]

        url_lower = url.lower()

        # Check skip patterns
        if any(pattern in url_lower for pattern in skip_patterns):
            return False

        # Apply site-specific rules if provided
        if site_rules:
            include_patterns = site_rules.get("include_patterns", [])
            exclude_patterns = site_rules.get("exclude_patterns", [])

            # Must match include patterns if specified
            if include_patterns and not any(
                pattern in url_lower for pattern in include_patterns
            ):
                return False

            # Must not match exclude patterns
            if any(pattern in url_lower for pattern in exclude_patterns):
                return False

        return True


class ContentExtractor:
    """Extracts structured content from HTML pages."""

    def __init__(
        self,
        user_agent: str = None,
        timeout: int = 10,
        use_mcmetadata: Optional[bool] = None,
        selenium_mode: Optional[str] = None,
    ):
        """Initialize ContentExtractor with anti-detection capabilities."""
        self.timeout = timeout  # Reduced from 20 for faster requests

        raw_mode_value = (
            selenium_mode or os.getenv("SELENIUM_EXECUTION_MODE") or "headful"
        )
        normalized_mode = raw_mode_value.strip().lower()
        if normalized_mode not in {"headful", "headless"}:
            logger.warning(
                "Invalid SELENIUM_EXECUTION_MODE '%s'; defaulting to headful",
                raw_mode_value,
            )
            normalized_mode = "headful"
        self.selenium_mode = normalized_mode
        logger.info("Selenium execution mode: %s", self.selenium_mode)

        raw_priority = os.getenv("SELENIUM_PRIMARY_STRATEGY", "http-first")
        normalized_priority = raw_priority.strip().lower()
        if normalized_priority not in {"http-first", "selenium-first"}:
            logger.warning(
                "Invalid SELENIUM_PRIMARY_STRATEGY '%s'; defaulting to http-first",
                raw_priority,
            )
            normalized_priority = "http-first"
        self._selenium_primary_strategy = normalized_priority

        # MediaCloud metadata integration (feature-flagged)
        if use_mcmetadata is None:
            env_value = os.getenv("ENABLE_MCMETADATA")
            if env_value is None:
                use_mcmetadata = True
            else:
                use_mcmetadata = env_value.lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                )

        self.use_mcmetadata = bool(use_mcmetadata)
        self.mcmetadata_include_other_metadata = os.getenv(
            "MCMETADATA_INCLUDE_OTHER", "true"
        ).lower() in ("1", "true", "yes", "on")

        # Reset per-extraction hints
        self._latest_wire_hints: Dict[str, Any] | None = None

        # CMS metadata extracted from JavaScript data objects (title, author, etc.)
        self._latest_cms_metadata: Dict[str, Any] | None = None

        # Track the most recent bot-protection detection to inform fallbacks
        self._last_bot_protection_detection: Optional[Dict[str, Any]] | None = None

        # Cache for wire author patterns from DB (5 min TTL)
        self._wire_author_patterns_cache: list[tuple[str, str, bool]] = []
        self._wire_author_patterns_timestamp: float = 0.0

        if self.use_mcmetadata and not MCMETADATA_AVAILABLE:
            logger.warning(
                "mcmetadata requested but package not available; disabling integration"
            )

        # Persistent driver for reuse across multiple extractions
        self._persistent_driver = None
        self._driver_creation_count = 0
        self._driver_reuse_count = 0
        # Max number of reuses before recreating driver to prevent memory leak
        # from accumulated Chrome renderer processes
        self._driver_reuse_limit = int(
            os.environ.get("SELENIUM_DRIVER_REUSE_LIMIT", "10")
        )

        # User agent pool for rotation - updated with latest browser versions
        # for better anti-detection (October 2025)
        self.user_agent_pool = [
            # Chrome on Windows (most common desktop browser)
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            # Chrome on macOS
            (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            # Chrome on Linux
            (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            # Firefox on Windows
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) "
                "Gecko/20100101 Firefox/130.0"
            ),
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) "
                "Gecko/20100101 Firefox/131.0"
            ),
            # Firefox on macOS
            (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) "
                "Gecko/20100101 Firefox/130.0"
            ),
            # Firefox on Linux
            (
                "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                "Gecko/20100101 Firefox/130.0"
            ),
            # Safari on macOS (latest versions)
            (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/18.0 Safari/605.1.15"
            ),
            (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.6 Safari/605.1.15"
            ),
            # Edge on Windows
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0"
            ),
        ]

        # Header variation pools for more realistic browser behavior
        self.accept_language_pool = [
            "en-US,en;q=0.9",
            "en-GB,en;q=0.9",
            "en-US,en;q=0.9,es;q=0.8",
            "en-US,en;q=0.9,fr;q=0.8,de;q=0.7",
            "en;q=0.9",
            "en-US,en;q=0.8",
            "en-US,en;q=0.7",
        ]

        self.accept_encoding_pool = [
            "gzip, deflate, br, zstd",
            "gzip, deflate, br",
            "gzip, deflate",
        ]

        # More realistic Accept header variations
        self.accept_header_pool = [
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        ]

        # Track domain-specific sessions and user agents
        self.domain_sessions: dict[str, Any] = {}
        self.domain_user_agents: dict[str, str] = {}
        self.request_counts: dict[str, int] = {}
        self.last_request_times: dict[str, float] = {}

        # Per-domain concurrency lock (ensure single in-flight per domain)
        self.domain_locks: dict[str, Any] = {}

        # Rate limiting and backoff management
        self.domain_request_times: dict[str, float] = (
            {}
        )  # Track last request time per domain
        self.domain_backoff_until: dict[str, float] = (
            {}
        )  # Track when domain is available again
        self.domain_error_counts: dict[str, int] = (
            {}
        )  # Track consecutive errors per domain

        try:
            self.unblock_rate_limit_seconds = float(
                os.getenv("UNBLOCK_RATE_LIMIT_SECONDS", "180")
            )
        except Exception:
            self.unblock_rate_limit_seconds = 180.0
        self._unblock_last_request_ts = 0.0
        self._unblock_rate_limit_lock = threading.Lock()

        # Selenium-specific failure tracking (separate from requests failures)
        # This prevents disabling Selenium for CAPTCHA-protected domains
        self._selenium_failure_counts: dict[str, int] = (
            {}
        )  # Track Selenium failures per domain

        # Base inter-request delay (env tunable)
        try:
            self.inter_request_min = float(os.getenv("INTER_REQUEST_MIN", "1.5"))
            self.inter_request_max = float(os.getenv("INTER_REQUEST_MAX", "3.5"))
        except Exception:
            self.inter_request_min, self.inter_request_max = 1.5, 3.5
        self.base_delay = max(self.inter_request_min, 0.5)
        self.max_backoff = 300  # Maximum backoff time (5 minutes)

        # CAPTCHA-aware backoff configuration
        try:
            self.captcha_backoff_base = int(os.getenv("CAPTCHA_BACKOFF_BASE", "600"))
            self.captcha_backoff_max = int(os.getenv("CAPTCHA_BACKOFF_MAX", "5400"))
        except Exception:
            self.captcha_backoff_base, self.captcha_backoff_max = 600, 5400

        # UA rotation policy (less frequent rotation)
        try:
            self.ua_rotation_base = int(os.getenv("UA_ROTATE_BASE", "9"))
            self.ua_rotation_jitter = float(os.getenv("UA_ROTATE_JITTER", "0.25"))
        except Exception:
            self.ua_rotation_base, self.ua_rotation_jitter = 9, 0.25

        # Negative cache for dead URLs (404/410)
        self.dead_urls: dict[str, float] = {}
        try:
            self.dead_url_ttl = int(os.getenv("DEAD_URL_TTL_SECONDS", "604800"))
        except Exception:
            self.dead_url_ttl = 604800

        # Optional proxy pool routing for requests
        pool_env = (os.getenv("PROXY_POOL", "") or "").strip()
        self.proxy_pool = (
            [p.strip() for p in pool_env.split(",") if p.strip()] if pool_env else []
        )
        self.domain_proxies: dict[str, str] = {}

        # Initialize multi-proxy manager
        self.proxy_manager = get_proxy_manager()

        # MODIFIED: Override to SQUID provider when using Squid proxy
        squid_proxy_url = os.getenv(
            "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
        )
        active_provider = self._resolve_active_proxy_provider()
        if squid_proxy_url and active_provider != ProxyProvider.SQUID:
            switch_provider = getattr(self.proxy_manager, "switch_provider", None)
            if callable(switch_provider):
                switch_provider(ProxyProvider.SQUID)
            else:
                # Test doubles may not implement switch_provider; coerce directly.
                cast(Any, self.proxy_manager).active_provider = ProxyProvider.SQUID
            active_provider = ProxyProvider.SQUID
            logger.info(
                f"🔀 Proxy provider overridden to SQUID (using {squid_proxy_url})"
            )

        logger.info(
            f"🔀 Proxy manager initialized with provider: " f"{active_provider.value}"
        )

        # MODIFIED: Use Squid proxy for all proxy traffic
        # All proxy traffic now routes through residential Squid proxy
        squid_proxy_url = os.getenv(
            "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
        )
        logger.info(f"All proxy traffic routing through Squid: {squid_proxy_url}")

        # Set initial user agent
        self.current_user_agent = user_agent or random.choice(self.user_agent_pool)

        # Initialize primary session
        self._create_new_session()

        # Track metadata about publish date extraction source
        self._publish_date_details: Optional[Dict[str, Any]] = None

        # Initialize bot sensitivity manager for adaptive crawling
        self.bot_sensitivity_manager = BotSensitivityManager()

        self._fingerprint_profile: FingerprintProfile | None = (
            load_fingerprint_profile()
        )

        profile_dir_env = os.getenv("SELENIUM_USER_DATA_DIR")
        self._selenium_profile_directory = os.getenv(
            "SELENIUM_PROFILE_DIRECTORY", "Default"
        )
        readonly_flag = os.getenv("SELENIUM_PROFILE_READONLY", "false").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        try:
            self._selenium_user_data_dir = prepare_user_data_dir(
                profile_dir_env,
                readonly=readonly_flag,
            )
        except FileNotFoundError as exc:
            logger.error("SELENIUM_USER_DATA_DIR was set but is invalid: %s", exc)
            raise

        logger.info("ContentExtractor initialized with user agent rotation enabled")

    def _create_new_session(self):
        """Create a new session with current user agent and clear cookies."""
        # Initialize cloudscraper session for better Cloudflare handling
        if CLOUDSCRAPER_AVAILABLE and cloudscraper is not None:
            self.session = cloudscraper.create_scraper()
            logger.info("🔧 Created new cloudscraper session (anti-Cloudflare enabled)")
        else:
            self.session = requests.Session()
            logger.info("🔧 Created new requests session (cloudscraper NOT available)")

        # Set headers with some randomization
        self._set_session_headers()

    def _set_session_headers(self):
        """Set randomized headers for the current session.

        CRITICAL: ALL traffic must go through Squid proxy. Direct connections are DISABLED.
        """
        headers = {
            "User-Agent": self.current_user_agent,
            "Accept": random.choice(self.accept_header_pool),
            "Accept-Language": random.choice(self.accept_language_pool),
            "Accept-Encoding": random.choice(self.accept_encoding_pool),
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

        # Randomly include DNT header (not all browsers send it)
        if random.random() > 0.3:  # 70% chance
            headers["DNT"] = "1"

        self.session.headers.update(headers)

        # CRITICAL: ALWAYS use Squid proxy for ALL connections
        squid_proxy_url = os.getenv(
            "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
        )
        squid_proxies = {"http": squid_proxy_url, "https": squid_proxy_url}
        self.session.proxies.update(squid_proxies)
        logger.info(f"🔀 Squid proxy ENFORCED for ALL connections: {squid_proxy_url}")

        logger.debug(
            f"Updated session headers with UA: {self.current_user_agent[:50]}..."
        )

    def _resolve_active_proxy_provider(self) -> ProxyProvider:
        """Return the active proxy provider even when tests stub the manager."""

        provider = getattr(self.proxy_manager, "active_provider", ProxyProvider.DIRECT)
        if isinstance(provider, ProxyProvider):
            return provider

        # Many tests stub active_provider with SimpleNamespace(value="...")
        raw_value = getattr(provider, "value", None)
        if isinstance(raw_value, str):
            for candidate in ProxyProvider:
                if candidate.value == raw_value.lower():
                    return candidate

        return ProxyProvider.DIRECT

    def _get_domain_session(self, url: str):
        """Get or create a domain-specific session with user agent rotation."""
        domain = urlparse(url).netloc

        # Check if domain is rate limited
        if self._check_rate_limit(domain):
            backoff_time = self.domain_backoff_until[domain] - time.time()
            logger.info(
                f"Domain {domain} is rate limited, backing off for "
                f"{backoff_time:.0f} more seconds"
            )
            raise RateLimitError(f"Domain {domain} is rate limited")

        # Check if we need to rotate user agent for this domain
        should_rotate = False

        if domain not in self.domain_sessions:
            # First request to this domain
            should_rotate = True
            self.request_counts[domain] = 0
        else:
            # Check rotation conditions
            self.request_counts[domain] += 1

            # Rotate every ~UA_ROTATE_BASE calls with jitter
            base_threshold = max(int(self.ua_rotation_base), 2)
            jitter = max(1, int(base_threshold * float(self.ua_rotation_jitter)))
            rotation_threshold = random.randint(
                base_threshold - jitter, base_threshold + jitter
            )
            if self.request_counts[domain] >= rotation_threshold:
                should_rotate = True
                self.request_counts[domain] = 0
                logger.info(
                    f"Rotating user agent for {domain} after "
                    f"{rotation_threshold} article calls"
                )

        if should_rotate:
            # Select new user agent (avoid repeating the same one.)
            available_agents = [
                ua
                for ua in self.user_agent_pool
                if ua != self.domain_user_agents.get(domain)
            ]
            new_user_agent = random.choice(available_agents)

            # Create new session with clean cookies
            session_type = None
            if CLOUDSCRAPER_AVAILABLE and cloudscraper is not None:
                new_session = cloudscraper.create_scraper()
                session_type = "cloudscraper"
            else:
                new_session = requests.Session()
                session_type = "requests"

            # Set randomized headers with more variation
            headers = {
                "User-Agent": new_user_agent,
                "Accept": random.choice(self.accept_header_pool),
                "Accept-Language": random.choice(self.accept_language_pool),
                "Accept-Encoding": random.choice(self.accept_encoding_pool),
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }

            # Randomly include DNT header (not all browsers send it)
            if random.random() > 0.3:  # 70% chance
                headers["DNT"] = "1"

            new_session.headers.update(headers)

            # CRITICAL: ALWAYS use Squid proxy for ALL connections (domain sessions too)
            squid_proxy_url = os.getenv(
                "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
            )
            squid_proxies = {"http": squid_proxy_url, "https": squid_proxy_url}
            new_session.proxies.update(squid_proxies)
            logger.debug(
                f"🔀 Squid proxy ENFORCED for domain session ({domain}): {squid_proxy_url}"
            )

            # Legacy proxy selection (DEPRECATED - Squid is now enforced)
            proxy = self._choose_proxy_for_domain(domain)
            if proxy:
                new_session.proxies.update(
                    {
                        "http": proxy,
                        "https": proxy,
                    }
                )

            # Store new session and user agent for this domain
            self.domain_sessions[domain] = new_session
            self.domain_user_agents[domain] = new_user_agent

            logger.info(
                f"🔧 Created {session_type} session for {domain} "
                f"(proxy: squid, "
                f"UA: {new_user_agent[:50]}...)"
            )
            logger.debug(f"Cleared cookies for domain {domain}")

        # Apply rate limiting delay before returning session
        self._apply_rate_limit(domain)

        return self.domain_sessions[domain]

    def _choose_proxy_for_domain(self, domain: str) -> Optional[str]:
        """Pick or return a sticky proxy for a domain if a pool is configured."""
        if not self.proxy_pool:
            return None
        proxy = self.domain_proxies.get(domain)
        if not proxy:
            proxy = random.choice(self.proxy_pool)
            self.domain_proxies[domain] = proxy
            logger.info(f"Assigned proxy for {domain}")
        return proxy

    def _generate_referer(self, url: str) -> Optional[str]:
        """Generate a realistic Referer header for the target URL.

        This makes requests look more natural, as if the user navigated
        from the site's homepage or another page on the same domain.
        """
        try:
            parsed = urlparse(url)
            scheme = parsed.scheme or "https"
            domain = parsed.netloc

            if not domain:
                return None

            # Randomly choose between different referer strategies
            strategy = random.choice(
                [
                    "homepage",  # 40% - from homepage
                    "homepage",
                    "same_domain",  # 30% - from another page on same domain
                    "same_domain",
                    "google",  # 20% - from Google search
                    "none",  # 10% - no referer
                ]
            )

            if strategy == "homepage":
                return f"{scheme}://{domain}/"
            elif strategy == "same_domain":
                # Reference another path on the same domain
                paths = ["/news", "/articles", "/local", "/sports", ""]
                return f"{scheme}://{domain}{random.choice(paths)}"
            elif strategy == "google":
                # Simulate coming from Google search
                return "https://www.google.com/"
            else:
                # No referer
                return None

        except Exception:
            return None

    def _get_domain_lock(self, domain: str) -> threading.Lock:
        """Return a lock object for the domain to cap concurrency to 1."""
        lock = self.domain_locks.get(domain)
        if lock is None:
            lock = threading.Lock()
            self.domain_locks[domain] = lock
        return lock

    def get_rotation_stats(self) -> Dict[str, Any]:
        """Get statistics about user agent rotation and session management."""
        return {
            "total_domains_accessed": len(self.domain_sessions),
            "active_sessions": len(self.domain_sessions),
            "domain_user_agents": {
                domain: ua[:50] + "..." if len(ua) > 50 else ua
                for domain, ua in self.domain_user_agents.items()
            },
            "request_counts": self.request_counts.copy(),
            "user_agent_pool_size": len(self.user_agent_pool),
        }

    def _check_rate_limit(self, domain: str) -> bool:
        """Check if domain is currently rate limited."""
        current_time = time.time()

        # Check if domain is in backoff period
        if domain in self.domain_backoff_until:
            if current_time < self.domain_backoff_until[domain]:
                return True  # Still in backoff period
            else:
                # Backoff period expired, clear it
                del self.domain_backoff_until[domain]

        return False

    def _apply_rate_limit(self, domain: str, delay: float = None) -> None:
        """Apply rate limiting delay for a domain using bot sensitivity."""
        current_time = time.time()

        if delay is None:
            # Get sensitivity-based configuration
            config = self.bot_sensitivity_manager.get_sensitivity_config(domain)
            low = config.get("inter_request_min", 1.0)
            high = config.get("inter_request_max", 2.5)
            delay = random.uniform(low, high)

        # Apply delay if needed
        if domain in self.domain_request_times:
            time_since_last = current_time - self.domain_request_times[domain]
            if time_since_last < delay:
                sleep_time = delay - time_since_last
                logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s for {domain}")
                time.sleep(sleep_time)

        # Update last request time
        self.domain_request_times[domain] = time.time()

    def _handle_rate_limit_error(
        self,
        domain: str,
        response: requests.Response = None,
        apply_backoff: bool = True,
    ) -> None:
        """Handle rate limit errors with exponential backoff.

        When apply_backoff is False we still increment error counters and log the
        event but we skip writing to domain_backoff_until so that fallback flows
        (e.g., Selenium) can proceed without being blocked mid-extraction.
        """
        current_time = time.time()

        # Initialize error count if needed
        if domain not in self.domain_error_counts:
            self.domain_error_counts[domain] = 0

        # Increment error count
        self.domain_error_counts[domain] += 1
        error_count = self.domain_error_counts[domain]

        # Calculate exponential backoff
        base_delay = 60  # 1 minute base delay
        max_delay = 3600  # 1 hour maximum delay
        backoff_delay = min(base_delay * (2 ** (error_count - 1)), max_delay)

        # Add some randomness to avoid thundering herd
        jitter = random.uniform(0.8, 1.2)
        final_delay = backoff_delay * jitter

        # Set backoff period when allowed (default). Some fallback paths need to
        # continue immediately, so honor apply_backoff flag for those scenarios.
        if apply_backoff:
            self.domain_backoff_until[domain] = current_time + final_delay

        # Log the rate limit
        retry_after_value: Optional[str] = None
        if response is not None:
            headers = getattr(response, "headers", None)
            if headers is not None:
                getter = getattr(headers, "get", None)
                raw_value = getter("retry-after") if callable(getter) else None
                if raw_value is not None:
                    retry_after_value = str(raw_value).strip()

        used_retry_after = False
        if retry_after_value:
            try:
                retry_seconds = int(float(retry_after_value))
                if apply_backoff:
                    logger.warning(
                        f"Rate limited by {domain}, server says retry "
                        f"after {retry_seconds}s, our backoff: "
                        f"{final_delay:.0f}s (attempt {error_count})"
                    )
                else:
                    logger.warning(
                        f"Rate limited by {domain}, server says retry after "
                        f"{retry_seconds}s (attempt {error_count}) "
                        f"but skipping domain backoff to allow fallback"
                    )
                used_retry_after = True
                # Use server's retry-after if it's longer than our backoff
                if apply_backoff and retry_seconds > final_delay:
                    self.domain_backoff_until[domain] = current_time + retry_seconds
            except (ValueError, TypeError):
                logger.debug(
                    "Invalid retry-after header %r from %s; using default backoff",
                    retry_after_value,
                    domain,
                )

        if not used_retry_after:
            if apply_backoff:
                logger.warning(
                    f"Rate limited by {domain}, backing off for "
                    f"{final_delay:.0f}s (attempt {error_count})"
                )
            else:
                logger.warning(
                    f"Rate limited by {domain}, observed during fallback "
                    f"(attempt {error_count}); skipping domain backoff"
                )

    def _reset_error_count(self, domain: str) -> None:
        """Reset error count for successful requests."""
        if domain in self.domain_error_counts:
            self.domain_error_counts[domain] = 0

    def _detect_bot_protection_in_response(
        self, response: requests.Response
    ) -> Optional[str]:
        """Detect bot protection mechanisms in HTTP response.

        This should primarily be used for non-200 responses (403, 503, etc.)
        where bot protection is blocking access. For 200 responses, let the
        content extraction proceed - if there's real bot protection, extraction
        will fail naturally without false positives.

        Returns a string identifying the specific protection type:
        - 'perimeterx' - Human Security / PerimeterX (requires JS + captcha)
        - 'cloudflare' - Cloudflare (may require JS challenge)
        - 'datadome' - DataDome bot protection
        - 'akamai' - Akamai Bot Manager
        - 'incapsula' - Imperva Incapsula
        - 'bot_protection' - Generic/unknown bot protection
        - None if no protection detected
        """
        if not response or not response.text:
            return None

        text_lower = response.text.lower()
        text_original = response.text

        # PerimeterX / Human Security - requires JS execution + captcha
        # These sites MUST use Selenium, HTTP will never work
        perimeterx_indicators = [
            "window._pxappid",
            "window._pxuuid",
            "px-captcha",
            "captcha.px-cloud.net",
            "humansecurity.com",
            "pxchk",
            "_pxhd",  # PerimeterX header cookie
        ]
        if any(indicator in text_lower for indicator in perimeterx_indicators):
            return "perimeterx"

        # DataDome bot protection
        datadome_indicators = [
            "datadome",
            "dd.js",
            "window.ddjskey",
            "geo.captcha-delivery.com",
        ]
        if any(indicator in text_lower for indicator in datadome_indicators):
            return "datadome"

        # Akamai Bot Manager
        akamai_indicators = [
            "akamai",
            "_abck",  # Akamai bot cookie
            "ak_bmsc",
            "sensor_data",
        ]
        if any(indicator in text_lower for indicator in akamai_indicators):
            return "akamai"

        # Imperva Incapsula
        incapsula_indicators = [
            "incapsula",
            "imperva",
            "visid_incap",
            "incap_ses",
        ]
        if any(indicator in text_lower for indicator in incapsula_indicators):
            return "incapsula"

        # Cloudflare protection indicators
        cloudflare_indicators = [
            "checking your browser",
            "cloudflare ray id",
            "ddos protection by cloudflare",
            "under attack mode",
            "attention required! | cloudflare",
            "just a moment...",
            "cf-ray",
        ]
        if any(indicator in text_lower for indicator in cloudflare_indicators):
            return "cloudflare"

        # Generic bot protection indicators (only check for active challenges)
        # Note: Exclude passive "grecaptcha" CSS/JS references
        bot_protection_indicators = [
            "access denied",
            "blocked by",
            "bot protection",
            "security check",
            "please wait while we verify",
            "browser check",
            "are you a robot",
            "please verify you are human",
            "please complete the captcha",
            "solve the captcha",
            "captcha challenge",
        ]
        if any(indicator in text_lower for indicator in bot_protection_indicators):
            return "bot_protection"

        # Check for suspiciously short responses (often challenge pages)
        if len(response.text) < 500 and response.status_code in [403, 503]:
            return "suspicious_short_response"

        return None

    def _is_js_required_protection(self, protection_type: Optional[str]) -> bool:
        """Check if protection type requires JavaScript execution.

        These protection types cannot be bypassed with HTTP requests alone,
        even with residential proxies. They require a real browser.
        """
        js_required_protections = {
            "perimeterx",
            "datadome",
            "akamai",
            "incapsula",
            "cloudflare",  # Cloudflare JS challenge
        }
        return protection_type in js_required_protections

    def _record_bot_protection_detection(
        self,
        *,
        protection_type: Optional[str],
        status_code: Optional[int],
        source: str,
    ) -> None:
        """Persist the latest bot-protection detection for downstream logic."""

        self._last_bot_protection_detection = {
            "type": protection_type,
            "status_code": status_code,
            "source": source,
        }

    def _mark_domain_special_extraction(
        self, domain: str, protection_type: str, method: str = "selenium"
    ) -> None:
        """Mark a domain as requiring special extraction method.

        Called when we detect bot protection that requires non-standard extraction.
        For strong protections like PerimeterX, use 'unblock' method with Squid proxy.
        For other JS protections, use 'selenium' method.

        Args:
            domain: Domain to mark
            protection_type: Type of bot protection detected
            method: Extraction method - 'selenium', 'unblock', or 'http'
        """
        from datetime import datetime

        from sqlalchemy import text

        from src.models.database import DatabaseManager

        # Map strong bot protections to the appropriate extraction method
        if protection_type == "perimeterx":
            # PerimeterX requires full-browser execution; skip HTTP entirely
            method = "selenium"
        elif protection_type in {"datadome", "akamai"}:
            method = "unblock"

        try:
            db = DatabaseManager()
            with db.get_session() as session:
                session.execute(
                    text(
                        """
                        UPDATE sources
                        SET extraction_method = :method,
                            selenium_only = :is_selenium,
                            bot_protection_type = :protection_type,
                            bot_protection_detected_at = :detected_at
                        WHERE host = :host
                        AND (extraction_method = 'http' OR extraction_method IS NULL)
                    """
                    ),
                    {
                        "host": domain,
                        "method": method,
                        "is_selenium": method == "selenium",
                        "protection_type": protection_type,
                        "detected_at": datetime.utcnow(),
                    },
                )
                session.commit()
                logger.info(
                    f"🔒 Marked {domain} with extraction_method={method} "
                    f"(protection: {protection_type})"
                )
        except Exception as e:
            logger.warning(f"Failed to mark {domain} extraction method: {e}")

    def _get_domain_extraction_method(self, domain: str) -> tuple[str, Optional[str]]:
        """Get the required extraction method for a domain.

        Returns:
            Tuple of (extraction_method, protection_type)
            extraction_method: 'http', 'selenium', or 'unblock'
        """
        # Check in-memory cache first
        cache_key = f"extraction_method:{domain}"
        cached = getattr(self, "_extraction_method_cache", {}).get(cache_key)
        if cached is not None:
            return cached

        try:
            from sqlalchemy import text

            from src.models.database import DatabaseManager

            db = DatabaseManager()
            with db.get_session() as session:
                row = session.execute(
                    text(
                        """
                        SELECT COALESCE(extraction_method, 'http'), bot_protection_type
                        FROM sources
                        WHERE host = :host
                    """
                    ),
                    {"host": domain},
                ).fetchone()

                if row:
                    result = (row[0] or "http", row[1])
                else:
                    result = ("http", None)

                # Cache the result
                if not hasattr(self, "_extraction_method_cache"):
                    self._extraction_method_cache = {}
                self._extraction_method_cache[cache_key] = result
                return result

        except Exception as e:
            logger.error(
                f"Failed to check extraction method for {domain}: {e}", exc_info=True
            )
            return ("http", None)

    def _handle_captcha_backoff(self, domain: str) -> None:
        """Apply extended backoff for CAPTCHA/challenge detections."""
        now = time.time()
        count = self.domain_error_counts.get(domain, 0) + 1
        self.domain_error_counts[domain] = count
        base = int(getattr(self, "captcha_backoff_base", 600))
        cap = int(getattr(self, "captcha_backoff_max", 5400))
        delay = min(base * (2 ** (count - 1)), cap)
        delay *= random.uniform(0.9, 1.3)
        self.domain_backoff_until[domain] = now + delay
        logger.warning(f"CAPTCHA backoff for {domain}: {int(delay)}s (attempt {count})")

    def _create_error_result(
        self, url: str, error_msg: str, metadata: Dict = None
    ) -> Dict[str, Any]:
        """Create a standardized error result."""
        # Record proxy failure for network/bot blocking errors
        if any(
            err in error_msg.lower()
            for err in ["bot protection", "cloudflare", "captcha", "403", "429"]
        ):
            self.proxy_manager.record_failure()

        return {
            "url": url,
            "title": "",
            "content": "",
            "author": [],
            "publish_date": None,
            "extraction_method": "error",
            "quality_score": 0.0,
            "success": False,
            "error": error_msg,
            "metadata": metadata or {},
        }

    def clear_all_sessions(self):
        """Clear all domain sessions and reset rotation state."""
        self.domain_sessions.clear()
        self.domain_user_agents.clear()
        self.request_counts.clear()
        self.last_request_times.clear()
        logger.info("Cleared all domain sessions and rotation state")

    def get_persistent_driver(self):
        """Get or create a persistent Selenium driver for reuse.

        Automatically recreates the driver after reaching the reuse limit
        to prevent memory leaks from accumulated Chrome renderer processes.
        """
        headless_mode = self._is_headless_selenium_mode()
        can_use_undetected = UNDETECTED_CHROME_AVAILABLE or self._is_method_overridden(
            "_create_undetected_driver"
        )
        can_use_stealth = SELENIUM_AVAILABLE or self._is_method_overridden(
            "_create_stealth_driver"
        )

        # Check if driver needs recreation due to reuse limit
        if (
            self._persistent_driver is not None
            and self._driver_reuse_count >= self._driver_reuse_limit
        ):
            logger.info(
                f"Driver reached reuse limit ({self._driver_reuse_limit}), "
                f"recreating to clean up renderer processes"
            )
            self.close_persistent_driver()

        if self._persistent_driver is None:
            logger.info("Creating new persistent ChromeDriver for reuse")
            try:
                # Try undetected-chromedriver first (most advanced)
                if can_use_undetected:
                    try:
                        self._persistent_driver = self._create_undetected_driver(
                            headless=headless_mode
                        )
                        self._driver_method = "undetected-chromedriver"
                    except Exception as uc_err:
                        logger.warning(
                            f"undetected-chromedriver failed to initialize: {uc_err}; "
                            "falling back to selenium-stealth"
                        )
                        if can_use_stealth:
                            self._persistent_driver = self._create_stealth_driver(
                                headless=headless_mode
                            )
                            self._driver_method = "selenium-stealth"
                        else:
                            raise
                elif can_use_stealth:
                    self._persistent_driver = self._create_stealth_driver(
                        headless=headless_mode
                    )
                    self._driver_method = "selenium-stealth"
                else:
                    raise Exception("No Selenium implementation available")

                self._driver_creation_count += 1
                logger.info(f"Created persistent driver using {self._driver_method}")

            except Exception as e:
                logger.error(f"Failed to create persistent driver: {e}")
                self._persistent_driver = None
                raise
        else:
            self._driver_reuse_count += 1
            logger.debug(
                f"Reusing persistent driver (reuse count: {self._driver_reuse_count})"
            )

        return self._persistent_driver

    def close_persistent_driver(self):
        """Close the persistent driver and clean up resources."""
        if self._persistent_driver is not None:
            try:
                logger.info(
                    f"Closing persistent driver after "
                    f"{self._driver_reuse_count + 1} uses "
                    f"(created {self._driver_creation_count} times)"
                )
                self._persistent_driver.quit()
            except Exception as e:
                logger.warning(f"Error closing persistent driver: {e}")
            finally:
                self._persistent_driver = None
                self._driver_reuse_count = 0

    def get_driver_stats(self) -> Dict[str, Any]:
        """Get statistics about driver usage."""
        return {
            "has_persistent_driver": self._persistent_driver is not None,
            "driver_creation_count": self._driver_creation_count,
            "driver_reuse_count": self._driver_reuse_count,
            "driver_reuse_limit": self._driver_reuse_limit,
            "driver_method": getattr(self, "_driver_method", None),
            "selenium_mode": self.selenium_mode,
        }

    def _is_method_overridden(self, method_name: str) -> bool:
        """Return True when an instance-level patch overrides a class method."""

        instance_method = getattr(self, method_name, None)
        class_method = getattr(self.__class__, method_name, None)
        if instance_method is None or class_method is None:
            return False

        instance_func = getattr(instance_method, "__func__", instance_method)
        class_func = getattr(class_method, "__func__", class_method)
        return instance_func is not class_func

    def _is_headless_selenium_mode(self) -> bool:
        return self.selenium_mode == "headless"

    def get_driver_telemetry_snapshot(
        self, domain: str | None = None
    ) -> Dict[str, Any]:
        """Return a JSON-safe telemetry snapshot for driver and proxy health."""

        snapshot: Dict[str, Any] = {
            "captured_at": datetime.utcnow().isoformat(),
            "driver": self.get_driver_stats(),
            "proxy": None,
        }

        try:
            active_provider = self._resolve_active_proxy_provider()
            proxy_info: Dict[str, Any] = {"active_provider": active_provider.value}
            proxy_manager = getattr(self, "proxy_manager", None)
            if proxy_manager is not None:
                config = proxy_manager.get_active_config()
                proxy_info.update(
                    {
                        "proxy_url": mask_proxy_url(getattr(config, "url", None)),
                        "success_count": getattr(config, "success_count", None),
                        "failure_count": getattr(config, "failure_count", None),
                        "success_rate": getattr(config, "success_rate", None),
                        "health": getattr(config, "health_status", None),
                    }
                )
            snapshot["proxy"] = proxy_info
        except Exception as exc:
            logger.debug("Unable to capture proxy telemetry snapshot: %s", exc)

        if domain:
            domain_info: Dict[str, Any] = {
                "name": domain,
                "error_count": self.domain_error_counts.get(domain),
                "selenium_failures": self._selenium_failure_counts.get(domain, 0),
            }

            backoff_until = self.domain_backoff_until.get(domain)
            if backoff_until:
                domain_info["backoff_until"] = datetime.utcfromtimestamp(
                    backoff_until
                ).isoformat()
                domain_info["captcha_backoff_active"] = time.time() < backoff_until
            else:
                domain_info["captcha_backoff_active"] = False

            if domain in self.domain_request_times:
                domain_info["last_request_age_sec"] = max(
                    0.0, time.time() - self.domain_request_times[domain]
                )

            snapshot["domain"] = domain_info

        return snapshot

    def extract_article_data(self, html: str, url: str) -> Dict[str, Any]:
        """Extract article metadata and content from HTML.

        Returns:
            Dictionary with extracted article data
        """
        if not html:
            return {}

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.error(f"Error parsing HTML for {url}: {e}")
            return {}

        data = {
            "url": url,
            "title": self._extract_title(soup),
            "author": self._extract_author(soup),
            # legacy name `published_date` kept for internal use; callers
            # expect `publish_date` so we expose both below when returning
            "published_date": self._extract_published_date(soup, html),
            "content": self._extract_content(soup),
            "meta_description": self._extract_meta_description(soup),
            "extracted_at": datetime.utcnow().isoformat(),
            "content_hash": None,  # Will be calculated later
        }

        # Calculate content hash
        if data["content"]:
            data["content_hash"] = hashlib.sha256(
                data["content"].encode("utf-8")
            ).hexdigest()

        return data

    def extract_content(
        self, url: str, html: str = None, metrics: Optional[ExtractionMetrics] = None
    ) -> Dict[str, Any]:
        """Fetch page if needed, extract article data using multiple methods.

        Uses intelligent field-level fallback:
        1. mcmetadata (if enabled) - extract all fields
        2. newspaper4k (primary legacy) - extract only missing fields
        3. BeautifulSoup (fallback) - extract remaining missing fields
        4. Selenium (final fallback) - extract only remaining missing fields

        Args:
            url: URL to extract content from
            html: Optional pre-fetched HTML content
            metrics: Optional ExtractionMetrics object for telemetry tracking

        Returns a dictionary with keys: title, author, content, publish_date,
        metadata (original meta), and extracted_at.
        """
        logger.debug(f"Starting content extraction for {url}")

        # Reset publish-date detail tracking for this article
        self._publish_date_details = None
        self._latest_wire_hints = None
        self._latest_cms_metadata = None
        self._last_bot_protection_detection = None

        # Initialize result structure
        result: Dict[str, Any] = {
            "url": url,
            "title": None,
            "author": None,
            "publish_date": None,
            "content": None,
            "metadata": {},
            "extracted_at": datetime.utcnow().isoformat(),
            "extraction_methods": {},  # Track which method worked for field
        }

        html_for_methods = html

        # Check if domain requires special extraction method
        domain = urlparse(url).netloc
        extraction_method, protection_type = self._get_domain_extraction_method(domain)
        skip_http_methods = extraction_method in {"selenium", "unblock"}

        selenium_first = self._should_prioritize_selenium(extraction_method)
        selenium_attempted_primary = False

        if selenium_first and SELENIUM_AVAILABLE:
            reason = (
                "domain_required"
                if extraction_method == "selenium"
                else "headful_primary"
            )
            attempted, success = self._run_selenium_extraction(
                url, result, metrics, reason
            )
            selenium_attempted_primary = attempted
            if success and not self._get_missing_fields(result):
                skip_http_methods = True
            self._apply_cms_metadata_fallback(result)

        if extraction_method == "unblock":
            logger.info(
                f"🔓 Domain {domain} uses unblock proxy extraction "
                f"(protection: {protection_type}) - using Squid proxy"
            )
        elif extraction_method == "selenium":
            logger.info(
                f"🔒 Domain {domain} uses Selenium extraction "
                f"(protection: {protection_type}) - skipping HTTP methods"
            )

        # Try mcmetadata first if enabled (skip for selenium_only domains)
        if self._mcmetadata_enabled() and not skip_http_methods:
            try:
                logger.info(f"Attempting mcmetadata extraction for {url}")
                if metrics:
                    metrics.start_method("mcmetadata")

                mcmetadata_result = self._extract_with_mcmetadata(
                    url,
                    html_for_methods,
                    include_other_metadata=self.mcmetadata_include_other_metadata,
                )

                if mcmetadata_result:
                    self._merge_extraction_results(
                        result, mcmetadata_result, "mcmetadata", None, metrics
                    )
                    logger.info(f"mcmetadata extraction completed for {url}")
                    if metrics:
                        metrics.end_method("mcmetadata", True, None, mcmetadata_result)
                else:
                    if metrics:
                        metrics.end_method(
                            "mcmetadata", False, "No content extracted", {}
                        )

            except Exception as e:  # pragma: no cover - network/parse variety
                logger.info(f"mcmetadata extraction failed for {url}: {e}")
                if metrics:
                    metrics.end_method("mcmetadata", False, str(e), {})

        # Determine what fields remain after mcmetadata
        missing_fields = self._get_missing_fields(result)

        # Try newspaper4k if mcmetadata is disabled or gaps remain
        # Skip for selenium_only domains - HTTP requests will fail
        use_newspaper = (
            NEWSPAPER_AVAILABLE
            and (not self._mcmetadata_enabled() or missing_fields)
            and not skip_http_methods
        )
        if use_newspaper:
            try:
                logger.info(f"Attempting newspaper4k extraction for {url}")
                if metrics:
                    metrics.start_method("newspaper4k")

                newspaper_result = self._extract_with_newspaper(url, html_for_methods)

                if newspaper_result:
                    self._merge_extraction_results(
                        result, newspaper_result, "newspaper4k", None, metrics
                    )
                    logger.info(f"newspaper4k extraction completed for {url}")
                    if metrics:
                        metrics.end_method("newspaper4k", True, None, newspaper_result)
                else:
                    if metrics:
                        metrics.end_method(
                            "newspaper4k",
                            False,
                            "No content extracted",
                            newspaper_result or {},
                        )

            except NotFoundError as e:
                logger.warning(f"URL not found (404/410), stopping extraction: {url}")
                if metrics:
                    metrics.end_method("newspaper4k", False, str(e), {})
                raise
            except RateLimitError as e:
                logger.warning(f"Rate limit/bot protection, stopping extraction: {url}")
                if metrics:
                    metrics.end_method("newspaper4k", False, str(e), {})
                raise
            except Exception as e:
                logger.info(f"newspaper4k extraction failed for {url}: {e}")

                error_str = str(e)

                import re

                partial_result: Dict[str, Any] = {}
                status_code = None
                status_match = re.search(r"Status code (\d+)", error_str)
                if status_match:
                    status_code = int(status_match.group(1))
                    partial_result = {
                        "metadata": {
                            "extraction_method": "newspaper4k",
                            "http_status": status_code,
                        }
                    }

                detection_info = self._last_bot_protection_detection
                protection_type = (
                    detection_info.get("type")
                    if detection_info and detection_info.get("type")
                    else None
                )
                bot_protection_failure = (
                    "Bot protection" in error_str
                    or "Server error (403)" in error_str
                    or (status_code in {401, 403, 429})
                    or detection_info is not None
                )
                if bot_protection_failure:
                    result["_bot_protection_detected"] = True
                    if not protection_type:
                        match = re.search(
                            r"Bot protection on [^:]+:\s*([a-z0-9_\-]+)",
                            error_str,
                            re.IGNORECASE,
                        )
                        if match:
                            protection_type = match.group(1).lower()

                    if protection_type:
                        result["_bot_protection_type"] = protection_type

                if hasattr(e, "__context__") and hasattr(e.__context__, "response"):
                    pass

                if metrics:
                    metrics.end_method("newspaper4k", False, str(e), partial_result)

        # Check what fields are still missing
        self._apply_cms_metadata_fallback(result)
        missing_fields = self._get_missing_fields(result)

        # Try BeautifulSoup fallback for missing fields
        # For selenium_only domains without pre-fetched HTML, skip to Selenium
        has_html_for_bs = html_for_methods or (result.get("metadata", {}).get("html"))
        if missing_fields and (has_html_for_bs or not skip_http_methods):
            try:
                logger.info(
                    f"Attempting BeautifulSoup fallback for missing "
                    f"fields {missing_fields} on {url}"
                )
                if metrics:
                    metrics.start_method("beautifulsoup")

                bs_result = self._extract_with_beautifulsoup(url, html)

                if bs_result:
                    # Only copy missing fields
                    self._merge_extraction_results(
                        result, bs_result, "beautifulsoup", missing_fields, metrics
                    )
                    logger.info(f"BeautifulSoup extraction completed for {url}")
                    if metrics:
                        metrics.end_method("beautifulsoup", True, None, bs_result)
                else:
                    if metrics:
                        metrics.end_method(
                            "beautifulsoup",
                            False,
                            "No content extracted",
                            bs_result or {},
                        )

            except RateLimitError as e:
                logger.warning(
                    "BeautifulSoup fallback hit rate limit for %s: %s", url, e
                )
                if metrics:
                    metrics.end_method("beautifulsoup", False, str(e), {})
                raise
            except NotFoundError as e:
                logger.warning(
                    "BeautifulSoup fallback encountered missing article for %s: %s",
                    url,
                    e,
                )
                if metrics:
                    metrics.end_method("beautifulsoup", False, str(e), {})
                raise
            except Exception as e:
                logger.info(f"BeautifulSoup extraction failed for {url}: {e}")
                if metrics:
                    metrics.end_method("beautifulsoup", False, str(e), {})

        # Check what fields are still missing after BeautifulSoup
        self._apply_cms_metadata_fallback(result)
        missing_fields = self._get_missing_fields(result)

        # For domains marked as 'unblock', use Squid proxy instead of Selenium
        if extraction_method == "unblock" and missing_fields:
            try:
                logger.info(
                    f"Attempting unblock proxy extraction for {url} "
                    f"(missing fields: {missing_fields})"
                )
                if metrics:
                    metrics.start_method("unblock_proxy")

                unblock_result = self._extract_with_unblock_proxy(url, None, metrics)

                if unblock_result and unblock_result.get("content"):
                    self._merge_extraction_results(
                        result, unblock_result, "unblock_proxy", missing_fields, metrics
                    )
                    logger.info(f"✅ Unblock proxy extraction succeeded for {url}")
                    if metrics:
                        metrics.end_method("unblock_proxy", True, None, unblock_result)
                else:
                    logger.warning(f"❌ Unblock proxy returned empty result for {url}")
                    if metrics:
                        metrics.end_method(
                            "unblock_proxy",
                            False,
                            "No content extracted",
                            unblock_result or {},
                        )

            except ProxyChallengeError as e:
                # Proxy challenge detected - do NOT fall back to Selenium
                # Re-raise to mark article for retry
                logger.warning(f"❌ Proxy challenge for {url}: {e}")
                if metrics:
                    metrics.end_method("unblock_proxy", False, str(e), {})
                raise  # Re-raise ProxyChallengeError to prevent Selenium fallback

            except Exception as e:
                logger.error(f"❌ Unblock proxy extraction failed for {url}: {e}")
                if metrics:
                    metrics.end_method("unblock_proxy", False, str(e), {})

        # Re-check missing fields after unblock attempt (ensure CMS metadata applied)
        self._apply_cms_metadata_fallback(result)
        missing_fields = self._get_missing_fields(result)

        # Try Selenium final fallback for remaining missing fields when not already attempted
        if missing_fields and SELENIUM_AVAILABLE and not selenium_attempted_primary:
            fallback_reason = (
                "selenium_secondary" if skip_http_methods else "http_fallback"
            )
            self._run_selenium_extraction(
                url,
                result,
                metrics,
                fallback_reason,
                missing_fields=missing_fields,
            )

        detection_info = self._last_bot_protection_detection
        # If bot protection was detected in newspaper4k and Selenium also failed, raise RateLimitError
        if (
            result.get("_bot_protection_detected") or detection_info
        ) and self._get_missing_fields(result):
            logger.warning(
                f"Bot protection detected and all fallbacks (including Selenium) failed for {url}"
            )
            domain = urlparse(url).netloc
            protection_type = result.get("_bot_protection_type")
            if not protection_type and detection_info:
                protection_type = detection_info.get("type")
            if protection_type and self._is_js_required_protection(protection_type):
                self._handle_captcha_backoff(domain)
            else:
                self._handle_rate_limit_error(domain)

            result["_bot_protection_detected"] = True
            if protection_type:
                result["_bot_protection_type"] = protection_type

            metadata = result.setdefault("metadata", {})
            metadata["bot_protection_blocked"] = True
            if protection_type:
                metadata["bot_protection_type"] = protection_type
            if detection_info and detection_info.get("status_code"):
                metadata["bot_protection_status"] = detection_info["status_code"]

            protection_label = protection_type or "bot_protection"
            self._last_bot_protection_detection = None
            raise RateLimitError(
                f"Bot protection blocked extraction for {domain} ({protection_label})"
            )

        # Clean up the flags if extraction succeeded
        result.pop("_bot_protection_detected", None)
        result.pop("_bot_protection_type", None)
        self._last_bot_protection_detection = None

        if self._latest_wire_hints:
            metadata = result.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                result["metadata"] = metadata

            existing_hints = metadata.get("wire_hints")
            if isinstance(existing_hints, dict):
                metadata["wire_hints"] = self._merge_wire_hints(
                    existing_hints, self._latest_wire_hints
                )
            else:
                metadata["wire_hints"] = deepcopy(self._latest_wire_hints)

        # Apply CMS metadata fallback for missing title/author
        self._apply_cms_metadata_fallback(result)

        # Apply URL-based publish date fallback when all methods fail
        if not result.get("publish_date"):
            url_fallback = self._extract_publish_date_from_url(url)
            if url_fallback:
                publish_date, pattern_name = url_fallback
                result["publish_date"] = publish_date
                result["extraction_methods"]["publish_date"] = "url_fallback"
                timestamp = datetime.utcnow().isoformat()
                self._record_publish_date_details(
                    "url_path",
                    {
                        "strategy": "url_pattern",
                        "pattern": pattern_name,
                        "applied_at": timestamp,
                    },
                )
                self._attach_publish_date_fallback_metadata(result)
                logger.info(
                    "Publish date derived from URL for %s using pattern %s",
                    url,
                    pattern_name,
                )

        # Log final extraction summary
        final_missing = self._get_missing_fields(result)
        if final_missing:
            logger.warning(
                f"Could not extract fields {final_missing} for {url} with any method"
            )
        else:
            logger.info(f"Successfully extracted all fields for {url}")

        # Complete extraction methods tracking for all fields
        self._complete_extraction_methods_tracking(result)

        # Determine the primary extraction method based on which extracted
        # the core content
        primary_method = self._determine_primary_extraction_method(result)

        # Clean up the metadata to remove internal tracking
        result_copy = result.copy()
        result_copy["metadata"]["extraction_methods"] = result["extraction_methods"]
        result_copy["metadata"]["extraction_method"] = primary_method
        del result_copy["extraction_methods"]

        # Prevent hints from leaking across articles
        self._latest_wire_hints = None
        self._latest_cms_metadata = None

        return result_copy

    def _mcmetadata_enabled(self) -> bool:
        """Return True when mcmetadata should run for this extractor."""

        return self.use_mcmetadata and MCMETADATA_AVAILABLE

    def _should_prioritize_selenium(self, extraction_method: str) -> bool:
        """Determine whether Selenium should run before HTTP methods."""
        if extraction_method == "unblock":
            # CRITICAL: unblock domains (PerimeterX, DataDome, Akamai) MUST try Selenium first
            # to defeat bot protection. Only fall back to proxy if Selenium fails.
            return True
        if extraction_method == "selenium":
            return True
        if self.selenium_mode == "headful":
            return True
        return self._selenium_primary_strategy == "selenium-first"

    def _get_missing_fields(self, result: Dict[str, Any]) -> List[str]:
        """Identify which fields are missing or empty in extraction result."""
        missing = []

        # Check title
        title = result.get("title")
        if not title or not str(title).strip():
            missing.append("title")

        # Check content (must have meaningful content, not just whitespace)
        content = result.get("content") or ""
        content = str(content).strip()
        if not content or len(content) < 50:  # Minimum content length
            missing.append("content")

        # Check author
        author = result.get("author")
        if not author or not str(author).strip():
            missing.append("author")

        # Check publish_date
        if not result.get("publish_date"):
            missing.append("publish_date")

        # Check metadata (should have some meaningful metadata)
        metadata = result.get("metadata", {})
        if not metadata or (isinstance(metadata, dict) and len(metadata) <= 1):
            # Empty or only has extraction_method
            missing.append("metadata")

        return missing

    def _extract_publish_date_from_url(self, url: str) -> Optional[Tuple[str, str]]:
        """Attempt to derive publish date directly from URL path."""
        parsed = urlparse(url)
        host = parsed.netloc.lower().split(":")[0]

        if not any(host.endswith(allowed) for allowed in URL_DATE_FALLBACK_HOSTS):
            return None

        slug = parsed.path.lower()
        if parsed.query:
            slug = f"{slug}?{parsed.query.lower()}"

        for pattern_name, pattern in URL_DATE_REGEX_PATTERNS:
            match = re.search(pattern, slug)
            if not match:
                continue

            try:
                year = int(match.group("year"))
                month = int(match.group("month"))
                day = int(match.group("day"))
            except (ValueError, KeyError):
                continue

            try:
                current_year = datetime.utcnow().year
                if not (2000 <= year <= current_year + 1):
                    continue

                publish_date = datetime(year, month, day).isoformat()
                return publish_date, pattern_name
            except ValueError:
                continue

        return None

    def _merge_extraction_results(
        self,
        target: Dict[str, Any],
        source: Dict[str, Any],
        method: str,
        fields_to_copy: Optional[List[str]] = None,
        metrics: Optional[object] = None,
        allow_overwrite: bool = False,
    ) -> None:
        """Merge source extraction results into target, tracking methods.

        Args:
            target: The target result dictionary to update
            source: The source result dictionary to copy from
            method: The extraction method name for tracking
            fields_to_copy: If specified, only copy these fields.
                           If None, copy all.
            metrics: Optional ExtractionMetrics for tracking alternatives
            allow_overwrite: When True, overwrite existing meaningful values
                             with the new method's results
        """
        if not source:
            return

        # Define all possible fields
        all_fields = ["title", "author", "content", "publish_date", "metadata"]

        # Determine which fields to process
        fields = fields_to_copy if fields_to_copy else all_fields

        for field in fields:
            source_value = source.get(field)
            if not self._is_field_value_meaningful(field, source_value):
                continue

            current_value = target.get(field)
            has_current_value = self._is_field_value_meaningful(field, current_value)

            if not has_current_value or allow_overwrite:
                target[field] = source_value
                target["extraction_methods"][field] = method
                if field == "publish_date":
                    self._merge_publish_date_fallback_metadata(target, source)
                logger.debug(
                    f"{'Overwrote' if has_current_value else 'Copied'} {field} from {method}"
                )
                continue

            if metrics and hasattr(metrics, "record_alternative_extraction"):
                metrics.record_alternative_extraction(
                    method, field, str(source_value), str(current_value)
                )
                logger.debug(
                    f"Alternative {field} found by {method} but not used "
                    f"(current from previous method)"
                )

    def _apply_cms_metadata_fallback(self, result: Dict[str, Any]) -> None:
        """Fill missing fields using CMS metadata captured during extraction."""
        if not self._latest_cms_metadata:
            return

        cms_meta = self._latest_cms_metadata
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            result["metadata"] = metadata

        cms_source = cms_meta.get("cms_source", "unknown")

        if not result.get("title") and cms_meta.get("title"):
            result["title"] = cms_meta["title"]
            result["extraction_methods"]["title"] = f"cms_{cms_source}"
            logger.info(
                "Title filled from CMS metadata (%s): %s",
                cms_meta.get("cms_source"),
                cms_meta["title"][:50] if cms_meta["title"] else None,
            )

        if not result.get("author") and cms_meta.get("author"):
            result["author"] = cms_meta["author"]
            result["extraction_methods"]["author"] = f"cms_{cms_source}"
            logger.info(
                "Author filled from CMS metadata (%s): %s",
                cms_meta.get("cms_source"),
                cms_meta["author"],
            )

        if not result.get("publish_date") and cms_meta.get("publish_date"):
            result["publish_date"] = cms_meta["publish_date"]
            result["extraction_methods"]["publish_date"] = f"cms_{cms_source}"

        metadata["cms_metadata_source"] = cms_meta.get("cms_source")
        if cms_meta.get("category"):
            metadata["cms_category"] = cms_meta["category"]

    def _is_field_value_meaningful(self, field: str, value: Any) -> bool:
        """Check if a field value is meaningful (not empty/null/trivial)."""
        if value is None:
            return False

        if field == "title":
            title_str = str(value).strip() if value else ""
            return bool(title_str and not self._is_title_suspicious(title_str))
        elif field == "content":
            content = str(value).strip() if value else ""
            return len(content) >= 50  # Minimum meaningful content length
        elif field == "author":
            return bool(value and str(value).strip())
        elif field == "publish_date":
            return bool(value)  # Any non-None date value is meaningful
        elif field == "metadata":
            if isinstance(value, dict):
                # Meaningful if has more than just extraction method tracking
                non_tracking_keys = [
                    k
                    for k in value.keys()
                    if k not in ["extraction_method", "extraction_methods"]
                ]
                return len(non_tracking_keys) > 0
            return bool(value)

        return bool(value)

    def _complete_extraction_methods_tracking(self, result: Dict[str, Any]):
        """Complete extraction methods tracking, mark missing as 'none'."""
        all_fields = ["title", "author", "content", "publish_date", "metadata"]
        extraction_methods = result.get("extraction_methods", {})

        for field in all_fields:
            if field not in extraction_methods:
                # Check if field has meaningful value
                field_value = result.get(field)
                if not self._is_field_value_meaningful(field, field_value):
                    extraction_methods[field] = "none"

        result["extraction_methods"] = extraction_methods

    def _determine_primary_extraction_method(self, result: Dict[str, Any]) -> str:
        """Determine primary extraction method based on core content.

        Priority: content > title > author > publish_date > metadata
        """
        extraction_methods = result.get("extraction_methods", {})

        # Priority order - most important fields first
        priority_fields = ["content", "title", "author", "publish_date", "metadata"]

        for field in priority_fields:
            method = extraction_methods.get(field)
            if method and method != "none":
                logger.debug(f"Primary extraction method: {method} (based on {field})")
                return method

        # Fallback to newspaper4k if no methods tracked
        logger.warning("No extraction methods tracked, defaulting to newspaper4k")
        return "newspaper4k"

    def _is_extraction_successful(self, result: Dict[str, Any]) -> bool:
        """Check if extraction result contains meaningful content."""
        if not result:
            return False

        # Must have at least title OR content
        title = result.get("title", "").strip()
        content = result.get("content", "").strip()

        return bool(title) or (bool(content) and len(content) > 100)

    def _extract_with_mcmetadata(
        self,
        url: str,
        html: Optional[str] = None,
        include_other_metadata: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Extract content using MediaCloud's mcmetadata pipeline.

        mcmetadata now includes structured data extraction (JSON-LD, meta tags)
        as the first step, which provides:
        - article_title (from JSON-LD headline or og:title)
        - article_author (from JSON-LD author or meta author)
        - publication_date (from JSON-LD datePublished or article:published_time)
        - wire_signals (from distributor tags, canonical URLs, etc.)
        """

        if not MCMETADATA_AVAILABLE:
            raise RuntimeError("mcmetadata library is not installed")

        include_other = (
            self.mcmetadata_include_other_metadata
            if include_other_metadata is None
            else include_other_metadata
        )

        stats_accumulator = {name: 0 for name in getattr(mcmetadata, "STAT_NAMES", [])}

        mc_result = mcmetadata.extract(
            url=url,
            html_text=html,
            include_other_metadata=include_other,
            stats_accumulator=stats_accumulator,
        )

        raw_html_snapshot = mc_result.pop("raw_html", None)

        # mcmetadata now handles wire detection via structured_data module
        # but we still call our additional detection for Hearst and other patterns
        self._update_wire_hints_from_html(raw_html_snapshot, url)

        # Merge wire signals from mcmetadata if present
        mc_wire_signals = mc_result.get("wire_signals")
        if mc_wire_signals and mc_wire_signals.get("detection_methods"):
            if self._latest_wire_hints:
                # Merge with existing hints
                existing_methods = self._latest_wire_hints.get("detected_by", [])
                existing_services = self._latest_wire_hints.get("wire_services", [])
                for method in mc_wire_signals.get("detection_methods", []):
                    if method not in existing_methods:
                        existing_methods.append(method)
                for service in mc_wire_signals.get("services", []):
                    if service not in existing_services:
                        existing_services.append(service)
                self._latest_wire_hints["detected_by"] = existing_methods
                self._latest_wire_hints["wire_services"] = existing_services
            else:
                self._latest_wire_hints = {
                    "detected_by": mc_wire_signals.get("detection_methods", []),
                    "wire_services": mc_wire_signals.get("services", []),
                    "raw_source_name": mc_wire_signals.get("services", []),
                    "evidence": mc_wire_signals.get("evidence", []),
                }

        text_content = mc_result.get("text_content")
        if isinstance(text_content, bytes):
            text_content = text_content.decode("utf-8", errors="ignore")
        if isinstance(text_content, str):
            text_content = text_content.strip()

        article_title = mc_result.get("article_title")

        # Use article_author from mcmetadata (now populated from structured data)
        author_value = mc_result.get("article_author")

        # Fall back to 'other' authors if article_author not set
        if not author_value and include_other:
            others = mc_result.get("other") or {}
            authors_raw = others.get("authors")
            if authors_raw:
                author_list: list[str] = []
                if isinstance(authors_raw, (list, tuple, set)):
                    for item in authors_raw:
                        if isinstance(item, str):
                            cleaned = item.strip()
                            if cleaned:
                                author_list.append(cleaned)
                elif isinstance(authors_raw, str):
                    cleaned = authors_raw.strip()
                    if cleaned:
                        author_list.append(cleaned)
                author_value = "; ".join(author_list) if author_list else None

        publish_date = mc_result.get("publication_date")
        if isinstance(publish_date, datetime):
            publish_date_value: Optional[str] = publish_date.isoformat()
        elif publish_date is not None:
            publish_date_value = str(publish_date)
        else:
            publish_date_value = None

        # Track extraction methods
        title_method = mc_result.get("title_extraction_method", "mcmetadata")
        author_method = mc_result.get("author_extraction_method")

        metadata_payload: Dict[str, Any] = {
            "extraction_method": "mcmetadata",
            "text_extraction_method": mc_result.get("text_extraction_method"),
            "title_extraction_method": title_method,
            "author_extraction_method": author_method,
        }

        mcmetadata_info = {
            "normalized_url": mc_result.get("normalized_url"),
            "canonical_url": mc_result.get("canonical_url"),
            "language": mc_result.get("language"),
            "stats": {k: float(v) for k, v in stats_accumulator.items()},
        }

        # Remove keys with falsy values to avoid cluttering metadata
        metadata_payload["mcmetadata"] = {
            key: value
            for key, value in mcmetadata_info.items()
            if value not in (None, "")
        }

        return {
            "url": mc_result.get("url") or url,
            "title": article_title,
            "author": author_value,
            "publish_date": publish_date_value,
            "content": text_content,
            "metadata": metadata_payload,
        }

    def _extract_with_newspaper(self, url: str, html: str = None) -> Dict[str, Any]:
        """Extract content using newspaper4k library with cloudscraper support."""
        # Skip if known-dead URL
        ttl = getattr(self, "dead_url_ttl", 0)
        if ttl and url in getattr(self, "dead_urls", {}):
            if time.time() < self.dead_urls[url]:
                logger.info(f"Skipping dead URL (cached): {url}")
                meta = {"status": 404}
                return self._create_error_result(url, "dead_url_cached", meta)

        article = NewspaperArticle(url, fetch_images=False)
        http_status = None
        # Initialize proxy metadata (will be populated if proxy is used)
        proxy_metadata = {
            "proxy_used": False,
            "proxy_url": None,
            "proxy_authenticated": False,
            "proxy_status": None,
            "proxy_error": None,
        }

        if html:
            # Use provided HTML
            article.html = html
        else:
            # Use domain-specific session to fetch HTML
            try:
                session = self._get_domain_session(url)
                domain = urlparse(url).netloc
                # Respect domain backoff
                if self._check_rate_limit(domain):
                    raise RateLimitError(f"Domain {domain} is rate limited")
                # Single in-flight per domain
                with self._get_domain_lock(domain):
                    logger.info(f"📡 Fetching {url[:80]}... via session for {domain}")

                    # Add Referer header for this specific request to look more natural
                    request_headers = {}
                    referer = self._generate_referer(url)
                    if referer:
                        request_headers["Referer"] = referer
                        logger.debug(f"Using Referer: {referer}")

                    response = session.get(
                        url, timeout=self.timeout, headers=request_headers
                    )
                http_status = response.status_code

                # Capture proxy metadata from response if available
                proxy_metadata = {
                    "proxy_used": getattr(response, "_proxy_used", False),
                    "proxy_url": getattr(response, "_proxy_url", None),
                    "proxy_authenticated": getattr(
                        response, "_proxy_authenticated", False
                    ),
                    "proxy_status": getattr(response, "_proxy_status", None),
                    "proxy_error": getattr(response, "_proxy_error", None),
                }

                # Log response details
                logger.info(
                    f"📥 Received {http_status} for {domain} "
                    f"(content: {len(response.text) if response.text else 0} bytes)"
                )

                # Check for rate limiting
                if response.status_code == 429:
                    logger.warning(f"Rate limited (429) by {domain}")
                    self._handle_rate_limit_error(domain, response)
                    # Record bot detection event
                    self.bot_sensitivity_manager.record_bot_detection(
                        host=domain,
                        url=url,
                        event_type="rate_limit_429",
                        http_status_code=429,
                    )
                    # Raise exception to stop all fallback attempts
                    raise RateLimitError(f"Rate limited (429) by {domain}")
                elif response.status_code in [401, 403, 502, 503, 504]:
                    # Detect specific bot protection type
                    protection_type = self._detect_bot_protection_in_response(response)

                    if protection_type:
                        logger.warning(
                            f"🚫 Bot protection detected ({response.status_code}, "
                            f"{protection_type}) by {domain}"
                        )

                        self._record_bot_protection_detection(
                            protection_type=protection_type,
                            status_code=response.status_code,
                            source="newspaper",
                        )

                        # If JS-required protection, mark domain with appropriate extraction method
                        # Strong protections (PerimeterX, DataDome) use 'unblock', others use 'selenium'
                        if self._is_js_required_protection(protection_type):
                            self._mark_domain_special_extraction(
                                domain, protection_type
                            )

                        # Record bot detection event
                        is_captcha = self._is_js_required_protection(protection_type)
                        event_type = (
                            "captcha_detected" if is_captcha else "403_forbidden"
                        )
                        self.bot_sensitivity_manager.record_bot_detection(
                            host=domain,
                            url=url,
                            event_type=event_type,
                            http_status_code=response.status_code,
                            response_indicators={"protection_type": protection_type},
                        )

                        # Use CAPTCHA backoff for confirmed bot protection
                        # Defer domain backoff until we know whether fallbacks
                        # succeed. We only apply captcha/rate-limit delays if
                        # every extraction path fails later in the pipeline.

                        # Raise regular Exception to allow Selenium fallback
                        # Only raise RateLimitError if ALL methods fail
                        raise Exception(
                            f"Bot protection on {domain}: "
                            f"{protection_type} ({response.status_code}) - will try Selenium"
                        )
                    else:
                        # Generic server error without bot protection indicators
                        logger.warning(
                            f"Server error ({response.status_code}) by {domain} "
                            f"- response preview: {response.text[:200] if response.text else 'empty'}"
                        )
                        self._handle_rate_limit_error(domain, response)
                        # Raise regular Exception to allow Selenium fallback
                        raise Exception(
                            f"Server error ({response.status_code}) on {domain} - will try Selenium"
                        )

                # Permanent missing -> cache as dead URL and raise exception
                if response.status_code in (404, 410):
                    if ttl:
                        self.dead_urls[url] = time.time() + ttl
                    logger.warning(
                        f"Permanent missing ({response.status_code}) for {url}; caching"
                    )
                    # Raise NotFoundError to stop all fallback attempts immediately
                    raise NotFoundError(f"URL returned {response.status_code}: {url}")

                # Check if request was successful
                if response.status_code == 200:
                    # Note: Removed aggressive bot protection check in 200 responses
                    # If page loaded successfully (200), attempt content extraction.
                    # Real bot protection will result in extraction failure naturally.
                    # False positives were causing legitimate pages to be incorrectly
                    # paused after Chromedriver/stealth updates.

                    # Reset error count on successful request
                    self._reset_error_count(domain)

                    # Record proxy success
                    response_time = response.elapsed.total_seconds()
                    self.proxy_manager.record_success(response_time=response_time)

                    # Use the downloaded HTML content to parse the article
                    article.html = response.text
                    ua = self.domain_user_agents.get(domain, "Unknown")
                    logger.info(
                        f"✅ Successfully fetched {len(response.text)} bytes from {domain} "
                        f"(UA: {ua[:30]}...)"
                    )
                elif 400 <= response.status_code < 500:
                    # All other 4xx client errors (besides those explicitly
                    # handled above). Examples: 400 Bad Request, 405 Method
                    # Not Allowed, 406 Not Acceptable, 408 Request Timeout,
                    # 451 Unavailable For Legal Reasons, etc.
                    logger.warning(
                        f"Client error ({response.status_code}) for {url}: "
                        f"{response.text[:200] if response.text else 'empty'}"
                    )
                    # Determine appropriate exception type
                    if response.status_code in (400, 405, 406, 451):
                        # Permanent client errors - treat like 404
                        if ttl:
                            self.dead_urls[url] = time.time() + ttl
                        raise NotFoundError(
                            f"Client error ({response.status_code}): {url}"
                        )
                    else:
                        # Other 4xx errors might be temporary (408, etc.)
                        raise RateLimitError(
                            f"Client error ({response.status_code}) on {domain}"
                        )
                elif 500 <= response.status_code < 600:
                    # All other 5xx server errors (besides 502, 503, 504
                    # handled above). Examples: 500 Internal Server Error,
                    # 501 Not Implemented, 505 HTTP Version Not Supported
                    logger.warning(
                        f"Server error ({response.status_code}) on {domain}: "
                        f"{response.text[:200] if response.text else 'empty'}"
                    )
                    self._handle_rate_limit_error(domain, response)
                    raise RateLimitError(
                        f"Server error ({response.status_code}) on {domain}"
                    )
                else:
                    # Unexpected status code (1xx, 3xx, or something else)
                    # 3xx should be handled automatically by requests, but just in case
                    logger.warning(
                        f"Unexpected status {response.status_code} for {url}"
                    )
                    raise RateLimitError(
                        f"Unexpected status ({response.status_code}) on {domain}"
                    )

            except RateLimitError:
                # Re-raise to stop all fallback attempts
                raise
            except NotFoundError:
                # Re-raise to stop all fallback attempts
                raise
            except Exception as e:
                logger.warning(
                    f"Session fetch failed for {url}: {e}, "
                    f"falling back to newspaper download"
                )
                # Fallback to newspaper4k's built-in download
                try:
                    article.download()
                except Exception as download_e:
                    # Try to extract HTTP status from newspaper4k error message
                    error_str = str(download_e)
                    if "Status code" in error_str:
                        import re

                        status_match = re.search(r"Status code (\d+)", error_str)
                        if status_match:
                            http_status = int(status_match.group(1))
                            logger.warning(
                                "Newspaper4k download failed with status %s: %s",
                                http_status,
                                error_str,
                            )
                            if http_status in {401, 403, 429}:
                                self._record_bot_protection_detection(
                                    protection_type=None,
                                    status_code=http_status,
                                    source="newspaper",
                                )
                    raise download_e

        article.parse()

        # Extract publish date if available
        publish_date = None
        if hasattr(article, "publish_date") and article.publish_date:
            publish_date = article.publish_date.isoformat()

        self._update_wire_hints_from_html(getattr(article, "html", None), url)

        return {
            "url": url,
            "title": article.title,
            "author": ", ".join(article.authors) if article.authors else None,
            "publish_date": publish_date,
            "content": article.text,
            "metadata": {
                "meta_description": article.meta_description,
                "keywords": article.keywords,
                "extraction_method": "newspaper4k",
                "cloudscraper_used": CLOUDSCRAPER_AVAILABLE
                and cloudscraper is not None,
                "http_status": http_status,
                **proxy_metadata,  # Include proxy metrics
            },
            "extracted_at": datetime.utcnow().isoformat(),
        }

    def _extract_with_beautifulsoup(self, url: str, html: str = None) -> Dict[str, Any]:
        """Extract content using BeautifulSoup with bot-avoidance."""
        # Lazily fetch HTML if not provided
        page_html = html
        if page_html is None:
            try:
                # Get domain-specific session with rotated user agent
                session = self._get_domain_session(url)

                # Additional headers for better bot-avoidance
                headers = {
                    "Accept": (
                        "text/html,application/xhtml+xml,"
                        "application/xml;q=0.9,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": random.choice(self.accept_language_pool),
                    "Accept-Encoding": random.choice(self.accept_encoding_pool),
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Cache-Control": "max-age=0",
                }

                # Temporarily update session headers (preserve existing)
                original_headers = session.headers.copy()
                session.headers.update(headers)

                try:
                    domain = urlparse(url).netloc
                    if self._check_rate_limit(domain):
                        raise RateLimitError(f"Domain {domain} is rate limited")
                    with self._get_domain_lock(domain):
                        resp = session.get(url, timeout=self.timeout)

                    if resp.status_code in (404, 410):
                        if getattr(self, "dead_url_ttl", 0):
                            self.dead_urls[url] = time.time() + self.dead_url_ttl
                        logger.warning(
                            f"Permanent missing ({resp.status_code}) for {url}; caching"
                        )
                        # Gracefully stop fallback attempts for true 404/410 responses
                        return {}

                    # Check for rate limiting and server errors
                    if resp.status_code == 429:
                        logger.warning(f"Rate limited (429) by {domain}")
                        raise RateLimitError(f"Rate limited (429) by {domain}")
                    elif resp.status_code in [401, 403, 502, 503, 504]:
                        protection_type = self._detect_bot_protection_in_response(resp)
                        if protection_type:
                            logger.warning(
                                f"🚫 Bot protection detected ({resp.status_code}, {protection_type}) by {domain} during BeautifulSoup fallback"
                            )
                            self._record_bot_protection_detection(
                                protection_type=protection_type,
                                status_code=resp.status_code,
                                source="beautifulsoup",
                            )
                            raise Exception(
                                f"Bot protection on {domain}: {protection_type} ({resp.status_code}) - will try Selenium"
                            )

                        logger.warning(f"Server error ({resp.status_code}) by {domain}")
                        raise Exception(
                            f"Server error ({resp.status_code}) on {domain} - will try Selenium"
                        )

                    resp.raise_for_status()
                    page_html = resp.text

                    ua = self.domain_user_agents.get(domain, "Unknown")
                    is_cloudscraper = (
                        CLOUDSCRAPER_AVAILABLE and cloudscraper is not None
                    )
                    logger.debug(
                        f"BeautifulSoup fetched {len(page_html)} chars "
                        f"from {url} (cloudscraper: {is_cloudscraper}, "
                        f"UA: {ua[:20]}...)"
                    )

                finally:
                    # Restore original headers
                    session.headers = original_headers

            except RateLimitError:
                # Propagate rate limiting up to extract_content so it can halt
                raise
            except NotFoundError:
                # Propagate permanent missing errors to stop fallback cascade
                raise
            except Exception as e:
                logger.warning(f"Failed to fetch page for extraction {url}: {e}")
                return {}

        self._update_wire_hints_from_html(page_html, url)

        raw = self.extract_article_data(page_html, url)

        # Normalize publish_date key: prefer `published_date` but expose
        # `publish_date` for downstream code consistency.
        publish_date = raw.get("published_date") or raw.get("publish_date")

        result = {
            "url": raw.get("url"),
            "title": raw.get("title"),
            "author": raw.get("author"),
            "publish_date": publish_date,
            "content": raw.get("content"),
            "metadata": {
                "meta_description": raw.get("meta_description"),
                "extraction_method": "beautifulsoup",
                "cloudscraper_used": (
                    CLOUDSCRAPER_AVAILABLE and cloudscraper is not None
                ),
            },
            "extracted_at": raw.get("extracted_at"),
        }

        self._attach_publish_date_fallback_metadata(result)

        return result

    def _extract_with_unblock_proxy(
        self,
        url: str,
        browser_actions: Optional[list] = None,
        metrics: Optional[ExtractionMetrics] = None,
    ) -> Dict[str, Any]:
        """Extract content using Squid proxy for strong bot protection.

        Routes requests through residential Squid proxy to bypass
        PerimeterX, DataDome, and other enterprise bot protections.

        Args:
            url: URL to extract

        Returns:
            Extraction result dict with title, author, content, etc.
        """
        try:
            import warnings

            warnings.filterwarnings("ignore", message="Unverified HTTPS request")

            # Route ALL unblock traffic through residential Squid proxy
            squid_proxy_url = os.getenv(
                "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
            )

            logger.info(f"Using Squid proxy for unblock extraction: {squid_proxy_url}")

            # Use Squid proxy directly (no authentication needed for this Squid setup)
            proxy_url = squid_proxy_url

            # Use standard browser headers for Squid proxy
            user_agent_pool = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ]
            user_agent = random.choice(user_agent_pool)

            # Standard browser headers for Squid proxy
            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "max-age=0",
            }

            logger.info(f"Fetching {url} via Squid proxy at {squid_proxy_url}")

            # Simple request through Squid proxy
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    proxies={"http": proxy_url, "https": proxy_url},
                    verify=False,
                    timeout=30,
                )

                html = response.text
                html_len = len(html)

                logger.info(
                    f"Squid proxy returned {html_len} bytes for {url} (status: {response.status_code})"
                )

                # Check for challenge page content patterns FIRST (before size check)
                html_lower = html.lower()
                challenge_patterns = [
                    "access denied",
                    "blocked by",
                    "access to this page has been denied",
                    "bot protection",
                    "security check",
                    "please wait while we verify",
                    "browser check",
                    "are you a robot",
                    "please verify you are human",
                    "please complete the captcha",
                    "solve the captcha",
                    "captcha challenge",
                    "attention required! cloudflare",
                    "just a moment...",
                    "checking your browser",
                ]

                if any(pattern in html_lower for pattern in challenge_patterns):
                    logger.warning(f"Challenge page detected for {url}: proxy blocked")
                    raise ProxyChallengeError(
                        f"Proxy challenge/block detected for {url}: challenge_page"
                    )

                # Check if extraction was successful (accept any successful response, not just 200)
                if response.status_code >= 400 or html_len < 1000:
                    logger.warning(
                        f"Squid proxy returned small/failed response for {url} (len={html_len}, status={response.status_code})"
                    )
                    raise ProxyChallengeError(
                        f"Proxy challenge/block detected for {url}: status_{response.status_code}"
                    )

                # Check for suspiciously short responses (often challenge pages)
                if html_len < 500 and response.status_code in [403, 503]:
                    logger.warning(
                        f"Suspicious short response for {url} (len={html_len}, status={response.status_code})"
                    )
                    raise ProxyChallengeError(
                        f"Proxy challenge/block detected for {url}: suspicious_short_response"
                    )

            except Exception as e:
                logger.error(f"Squid proxy request failed for {url}: {e}")
                # Don't wrap ProxyChallengeError - let it pass through with original message
                if isinstance(e, ProxyChallengeError):
                    raise e
                raise ProxyChallengeError(
                    f"Proxy challenge/block detected for {url}: {type(e).__name__}"
                )

            # Extract content using newspaper3k from the HTML
            try:
                from newspaper import Article

                article = Article(url)
                # Set the HTML content directly
                article.download_state = 2  # Article.ArticleDownloadState.SUCCESS
                article.html = html
                article.parse()

                # Build result dict
                result = {
                    "url": url,
                    "title": article.title or "",
                    "content": article.text or "",
                    "author": ", ".join(article.authors) if article.authors else "",
                    "publish_date": (
                        article.publish_date.isoformat() if article.publish_date else ""
                    ),
                    "method": "squid_proxy",
                }

                logger.info(
                    f"✅ Squid proxy extraction successful for {url}: {len(result['content'])} chars"
                )
                return result

            except Exception as e:
                logger.error(f"Content parsing failed for {url}: {e}")
                return {
                    "url": url,
                    "title": "",
                    "content": "",
                    "author": "",
                    "publish_date": "",
                    "method": "squid_proxy",
                }

        except Exception as e:
            logger.error(f"Squid proxy extraction failed for {url}: {e}")
            # Don't wrap ProxyChallengeError - let it pass through with original message
            if isinstance(e, ProxyChallengeError):
                raise e
            raise ProxyChallengeError(
                f"Proxy challenge/block detected for {url}: {str(e)}"
            )

    def _extract_with_selenium(self, url: str) -> Dict[str, Any]:
        """Extract content using persistent Selenium driver."""
        try:
            # Get the persistent driver (creates one if needed)
            driver = self.get_persistent_driver()
            stealth_method = getattr(self, "_driver_method", "unknown")

            logger.debug(f"Using persistent {stealth_method} driver for {url}")

            # Navigate with human-like behavior
            success = self._navigate_with_human_behavior(driver, url)
            if not success:
                return {}

            # Extract content after ensuring page is loaded
            html = driver.page_source

            self._update_wire_hints_from_html(html, url)

            # Stop page load immediately after getting HTML to prevent
            # waiting for slow ads/trackers (fixes 147s timeout issue)
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass  # Ignore if page already finished loading

            soup = BeautifulSoup(html, "html.parser")

            result: Dict[str, Any] = {
                "url": url,
                "title": self._extract_title(soup),
                "author": self._extract_author(soup),
                "publish_date": self._extract_published_date(soup, html),
                "content": self._extract_content(soup),
                "metadata": {
                    "meta_description": self._extract_meta_description(soup),
                    "extraction_method": "selenium",
                    "stealth_mode": True,
                    "stealth_method": stealth_method,
                    "page_source_length": len(html),
                    "driver_reused": self._driver_reuse_count > 0,
                },
                "extracted_at": datetime.utcnow().isoformat(),
            }

            metadata = cast(Dict[str, Any], result["metadata"])

            if self._fingerprint_profile:
                metadata["fingerprint_profile"] = (
                    self._fingerprint_profile.source_path.name
                )
            if self._selenium_user_data_dir:
                metadata.update(
                    {
                        "chrome_user_data_dir": str(self._selenium_user_data_dir),
                        "chrome_profile_directory": self._selenium_profile_directory,
                    }
                )

            self._attach_publish_date_fallback_metadata(result)

            return result

        except Exception as e:
            logger.error(f"Selenium extraction failed for {url}: {e}")
            # If the driver fails, close it so a new one will be created next
            # time
            if "driver" in str(e).lower() or "session" in str(e).lower():
                logger.warning("Driver error detected, closing persistent driver")
                self.close_persistent_driver()
            return {}

    def _run_selenium_extraction(
        self,
        url: str,
        result: Dict[str, Any],
        metrics: Optional[ExtractionMetrics],
        reason: str,
        missing_fields: Optional[List[str]] = None,
    ) -> Tuple[bool, bool]:
        """Run Selenium extraction and merge results.

        Returns (attempted, success) so callers can avoid duplicate work.
        """
        if not SELENIUM_AVAILABLE:
            return False, False

        fields_needed = missing_fields or self._get_missing_fields(result)
        if not fields_needed:
            return False, False

        dom = urlparse(url).netloc
        logger.info(
            "Attempting Selenium (%s) for missing fields %s on %s",
            reason,
            fields_needed,
            url,
        )

        if metrics:
            metrics.start_method("selenium")

        try:
            if self._check_rate_limit(dom):
                logger.info(
                    "Skipping Selenium for %s - domain is in CAPTCHA backoff period",
                    dom,
                )
                raise RateLimitError(f"Domain {dom} is in backoff period")

            selenium_failures = getattr(self, "_selenium_failure_counts", {})
            if selenium_failures.get(dom, 0) >= 3:
                logger.warning(
                    "Skipping Selenium for %s - already failed %s times",
                    dom,
                    selenium_failures[dom],
                )
                raise RateLimitError(f"Selenium repeatedly failed for {dom}; skipping")

            selenium_result = self._extract_with_selenium(url)
            if selenium_result:
                metadata = selenium_result.setdefault("metadata", {})
                metadata["selenium_reason"] = reason

            if selenium_result and selenium_result.get("content"):
                preferred_fields = list(
                    dict.fromkeys(
                        (fields_needed or [])
                        + ["title", "author", "content", "metadata"]
                    )
                )
                self._merge_extraction_results(
                    result,
                    selenium_result,
                    "selenium",
                    fields_to_copy=preferred_fields,
                    metrics=metrics,
                    allow_overwrite=True,
                )
                logger.info("✅ Selenium extraction succeeded for %s", url)
                if dom in self._selenium_failure_counts:
                    del self._selenium_failure_counts[dom]
                if metrics:
                    metrics.end_method("selenium", True, None, selenium_result)
                return True, True

            self._selenium_failure_counts[dom] = (
                self._selenium_failure_counts.get(dom, 0) + 1
            )
            logger.warning(
                "❌ Selenium returned empty result for %s (failure #%s)",
                url,
                self._selenium_failure_counts[dom],
            )
            if metrics:
                metrics.end_method(
                    "selenium",
                    False,
                    "No content extracted",
                    selenium_result or {},
                )
            return True, False

        except Exception as exc:
            self._selenium_failure_counts[dom] = (
                self._selenium_failure_counts.get(dom, 0) + 1
            )
            logger.info(
                "❌ Selenium extraction failed for %s: %s (failure #%s)",
                url,
                exc,
                self._selenium_failure_counts[dom],
            )
            if metrics:
                metrics.end_method("selenium", False, str(exc), {})
            return True, False

    def _resolve_selenium_user_agent(self) -> str:
        if self._fingerprint_profile and self._fingerprint_profile.user_agent:
            return self._fingerprint_profile.user_agent
        return random.choice(_SELENIUM_DEFAULT_USER_AGENTS)

    def _resolve_window_size(self) -> tuple[int, int]:
        if self._fingerprint_profile and self._fingerprint_profile.screen_size:
            return self._fingerprint_profile.screen_size
        width = random.randint(1366, 1920)
        height = random.randint(768, 1080)
        return width, height

    def _maybe_configure_user_data_dir(self, chrome_options) -> None:
        if not self._selenium_user_data_dir:
            return
        chrome_options.add_argument(f"--user-data-dir={self._selenium_user_data_dir}")
        if self._selenium_profile_directory:
            chrome_options.add_argument(
                f"--profile-directory={self._selenium_profile_directory}"
            )

    def _apply_fingerprint_profile(self, driver) -> None:
        profile = self._fingerprint_profile
        if not profile:
            return

        payload: dict[str, Any] = {}
        if profile.user_agent:
            payload["userAgent"] = profile.user_agent
        if profile.client_hints:
            payload.update(profile.client_hints)
        if payload:
            try:
                driver.execute_cdp_cmd("Network.setUserAgentOverride", payload)
            except Exception as exc:
                logger.debug("CDP UA override failed: %s", exc)

        if profile.accept_language:
            try:
                driver.execute_cdp_cmd(
                    "Network.setExtraHTTPHeaders",
                    {"headers": {"Accept-Language": profile.accept_language}},
                )
            except Exception as exc:
                logger.debug("Failed to set Accept-Language header: %s", exc)

        if profile.script:
            try:
                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": profile.script},
                )
            except Exception as exc:
                logger.debug("Fingerprint init script registration failed: %s", exc)

    def _create_undetected_driver(self, *, headless: bool | None = None):
        """Create undetected-chromedriver instance with maximum stealth."""
        headless_mode = (
            headless if headless is not None else self._is_headless_selenium_mode()
        )

        # Configure undetected chrome options
        options = uc.ChromeOptions()

        # Set page load strategy to 'eager' - don't wait for all resources
        # This stops waiting once DOM is interactive, not fully loaded
        # Prevents 147s timeouts waiting for slow ads/trackers
        options.page_load_strategy = "eager"

        # Basic stealth options
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=VizDisplayCompositor")
        # Don't disable extensions - we use proxy auth extension
        # options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        if headless_mode:
            options.add_argument("--headless=new")
        # Additional flags for containerized environments
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--remote-debugging-port=9222")
        # Note: JavaScript and images enabled for modern news sites

        width, height = self._resolve_window_size()
        options.add_argument(f"--window-size={width},{height}")

        # CRITICAL: Explicitly set realistic user agent to hide headless indicator
        # UC's auto-handling leaks "HeadlessChrome" in the UA string which PerimeterX detects
        realistic_ua = self._resolve_selenium_user_agent()
        options.add_argument(f"--user-agent={realistic_ua}")

        # CRITICAL: Configure proxy with authentication for PerimeterX bypass
        # PerimeterX blocks GKE datacenter IPs, residential proxy required
        # Use Chrome extension for proxy auth (standard approach)
        # CRITICAL: ALWAYS use Squid proxy - no direct connections allowed
        selenium_proxy = os.getenv(
            "SELENIUM_PROXY",
            os.getenv("SQUID_PROXY_URL", "http://t9880447.eero.online:3128"),
        )
        proxy_extension_path = None

        # Parse proxy URL: https://user:pass@host:port or http://host:port
        import re

        proxy_match = re.match(
            r"https?://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)", selenium_proxy
        )
        if proxy_match:
            proxy_user, proxy_pass, proxy_host, proxy_port = proxy_match.groups()

            # If proxy has authentication, create Chrome extension
            if proxy_user and proxy_pass:

                # Create Chrome extension for proxy authentication
                import tempfile
                import zipfile

                manifest_json = """{
                    "version": "1.0.0",
                    "manifest_version": 2,
                    "name": "Chrome Proxy Auth",
                    "permissions": ["proxy", "tabs", "unlimitedStorage", "storage", "<all_urls>", "webRequest", "webRequestBlocking"],
                    "background": {"scripts": ["background.js"]},
                    "minimum_chrome_version": "76.0.0"
                }"""

                background_js = f"""
                var config = {{
                    mode: "fixed_servers",
                    rules: {{
                        singleProxy: {{
                            scheme: "http",
                            host: "{proxy_host}",
                            port: parseInt({proxy_port})
                        }},
                        bypassList: ["localhost"]
                    }}
                }};

                chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

                function callbackFn(details) {{
                    return {{
                        authCredentials: {{
                            username: "{proxy_user}",
                            password: "{proxy_pass}"
                        }}
                    }};
                }}

                chrome.webRequest.onAuthRequired.addListener(
                    callbackFn,
                    {{urls: ["<all_urls>"]}},
                    ['blocking']
                );
                """

                # Create extension zip file
                proxy_extension_path = tempfile.mktemp(suffix=".zip")
                with zipfile.ZipFile(proxy_extension_path, "w") as zp:
                    zp.writestr("manifest.json", manifest_json)
                    zp.writestr("background.js", background_js)

                options.add_extension(proxy_extension_path)
                logger.debug(
                    f"Configured proxy extension for {proxy_host}:{proxy_port}"
                )
            else:
                # Proxy without authentication - use --proxy-server argument
                options.add_argument(f"--proxy-server={selenium_proxy}")
                logger.debug(
                    f"Configured Squid proxy via --proxy-server: {selenium_proxy}"
                )
        else:
            logger.error(
                f"Could not parse proxy URL: {mask_proxy_url(selenium_proxy)} - Selenium connections will FAIL"
            )

        self._maybe_configure_user_data_dir(options)

        # Read optional binary paths from environment
        # Common envs: CHROME_BIN, GOOGLE_CHROME_BIN, CHROMEDRIVER_PATH
        chrome_bin = os.getenv("CHROME_BIN") or os.getenv("GOOGLE_CHROME_BIN") or None
        driver_path = os.getenv("CHROMEDRIVER_PATH") or None

        # Note: For undetected-chromedriver, we pass browser_executable_path as a parameter
        # to the uc.Chrome() constructor (below) instead of setting options.binary_location.
        # Setting both causes "Binary Location Must be a String" errors.

        # Create driver with version management
        try:
            uc_kwargs = {
                "options": options,
                "version_main": None,  # Auto-detect
                "headless": headless_mode,
                # Changed to False for container stability
                "use_subprocess": False,
                "log_level": 3,  # Suppress logs
            }
            if driver_path:
                uc_kwargs["driver_executable_path"] = str(driver_path)
            if chrome_bin:
                uc_kwargs["browser_executable_path"] = str(chrome_bin)

            driver = uc.Chrome(**uc_kwargs)
        except Exception as e:
            logger.warning(f"Failed to create undetected driver: {e}")
            raise
        finally:
            # Clean up temporary proxy extension file
            if proxy_extension_path and os.path.exists(proxy_extension_path):
                try:
                    os.unlink(proxy_extension_path)
                except Exception:
                    pass  # Non-critical cleanup

        # Set timeouts - reduced for faster extraction
        driver.set_page_load_timeout(15)  # Reduced from 30
        driver.implicitly_wait(5)  # Reduced from 10

        self._apply_fingerprint_profile(driver)

        # CRITICAL: Override User-Agent via CDP to hide headless indicator
        # The command-line arg doesn't always take effect, CDP is more reliable
        try:
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {"userAgent": realistic_ua},
            )
        except Exception as e:
            logger.debug(f"CDP UA override failed (non-fatal): {e}")

        # Apply additional selenium-stealth for maximum anti-detection
        # undetected-chromedriver handles basic stealth, but PerimeterX needs more
        if SELENIUM_STEALTH_AVAILABLE:
            try:
                stealth(
                    driver,
                    languages=["en-US", "en"],
                    vendor="Google Inc.",
                    platform="Win32",
                    webgl_vendor="Intel Inc.",
                    renderer="Intel Iris OpenGL Engine",
                    fix_hairline=True,
                )
                logger.debug("Applied selenium-stealth to undetected driver")
            except Exception as e:
                logger.debug(f"selenium-stealth application failed (non-fatal): {e}")

        # Manual stealth enhancements for PerimeterX bypass
        try:
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            driver.execute_script(
                """
                // Override plugins to appear more legitimate
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });

                // Override languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });

                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
                """
            )
        except Exception as e:
            logger.debug(f"Manual stealth enhancements failed (non-fatal): {e}")

        # CRITICAL FIX: Set command executor timeout to prevent 147s delays
        # Default timeout is 120s, but Selenium waits an additional ~27s
        # somewhere, resulting in consistent 147s extractions. Setting to 30s
        # reduces this to ~0.4s.
        driver.command_executor._client_config.timeout = 30

        return driver

    def _create_stealth_driver(self, *, headless: bool | None = None):
        """Create regular Selenium driver with stealth enhancements."""
        headless_mode = (
            headless if headless is not None else self._is_headless_selenium_mode()
        )

        # Configure Chrome options for maximum stealth
        chrome_options = ChromeOptions()

        # Set page load strategy to 'eager' - don't wait for all resources
        # This stops waiting once DOM is interactive, not fully loaded
        # Prevents 147s timeouts waiting for slow ads/trackers
        chrome_options.page_load_strategy = "eager"

        if headless_mode:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")

        width, height = self._resolve_window_size()
        chrome_options.add_argument(f"--window-size={width},{height}")

        # Realistic user agent
        realistic_ua = self._resolve_selenium_user_agent()
        chrome_options.add_argument(f"--user-agent={realistic_ua}")

        # CRITICAL: ALWAYS use Squid proxy for Selenium - no direct connections allowed
        selenium_proxy = os.getenv(
            "SELENIUM_PROXY",
            os.getenv("SQUID_PROXY_URL", "http://t9880447.eero.online:3128"),
        )
        chrome_options.add_argument(f"--proxy-server={selenium_proxy}")
        logger.debug(f"Squid proxy ENFORCED for stealth driver: {selenium_proxy}")

        # Exclude automation switches
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # Additional prefs
        prefs = {
            "profile.default_content_setting_values": {
                "notifications": 2,
                "geolocation": 2,
                "media_stream": 2,
            },
            # Note: Allow images for better site compatibility
            # Some sites check image loading as bot detection
        }
        chrome_options.add_experimental_option("prefs", prefs)

        # Create driver
        chrome_bin = os.getenv("CHROME_BIN") or os.getenv("GOOGLE_CHROME_BIN") or None
        driver_path = os.getenv("CHROMEDRIVER_PATH") or None

        if chrome_bin:
            chrome_options.binary_location = str(chrome_bin)

        self._maybe_configure_user_data_dir(chrome_options)

        if driver_path:
            service = ChromeService(executable_path=str(driver_path))
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)

        # Apply selenium-stealth if available
        if SELENIUM_STEALTH_AVAILABLE:
            stealth(
                driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )

        # Manual stealth enhancements
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        driver.execute_script(
            """
            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Override platform
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });

            // Override permission API
            Object.defineProperty(navigator, 'permissions', {
                get: () => undefined
            });
        """
        )

        # Set timeouts - reduced for faster extraction
        driver.set_page_load_timeout(15)  # Reduced from 30
        driver.implicitly_wait(5)  # Reduced from 10

        self._apply_fingerprint_profile(driver)

        # CRITICAL FIX: Set command executor timeout to prevent 147s delays
        # Default timeout is 120s, but Selenium waits an additional ~27s
        # somewhere, resulting in consistent 147s extractions. Setting to 30s
        # reduces this to ~0.4s.
        driver.command_executor._client_config.timeout = 30

        return driver

    def _navigate_with_human_behavior(self, driver, url: str) -> bool:
        """Navigate to URL with minimal delays for faster content extraction."""
        try:
            # Navigate directly to target URL (no need for about:blank delay)
            domain = urlparse(url).netloc
            # Ensure single Selenium navigation per domain
            lock = self._get_domain_lock(domain)
            with lock:
                driver.get(url)

            # Wait for basic page load with shorter timeout
            WebDriverWait(driver, 5).until(  # Reduced from 10
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Quick wait for page to stabilize
            time.sleep(0.5)  # Reduced from 1.0-2.0 seconds

            # NEW: Check for actual CAPTCHA or bot challenges BEFORE subscription wall
            # This prevents false positive subscription wall detections on challenge pages
            if self._detect_captcha_or_challenge(driver):
                logger.warning(f"CAPTCHA or bot challenge detected on {url}")

                # Try to bypass the challenge (click buttons, wait for JS)
                if self._try_bypass_challenge(driver, url):
                    logger.info(f"Successfully bypassed challenge on {url}")
                    # After bypass, check if we're still on a subscription wall
                    if not self._detect_subscription_wall(driver):
                        return True
                
                # Try closing modals in case CAPTCHA is in a modal
                if self._try_close_modals(driver, url):
                    logger.info("Successfully closed CAPTCHA modal")
                    if not self._detect_subscription_wall(driver):
                        return True

            # Try to close subscription modals/popups
            # Prevents false positives from subscription walls
            modal_closed = self._try_close_modals(driver, url)

            # Check for subscription wall (separate from CAPTCHA)
            if self._detect_subscription_wall(driver):
                logger.warning(
                    f"Subscription wall detected on {url} "
                    f"(modal_closed={modal_closed})"
                )
                if modal_closed:
                    logger.info(
                        "Subscription modal already closed; continuing extraction"
                    )
                    return True

                # Try closing again if not already attempted
                if self._try_close_modals(driver, url):
                    logger.info("Successfully closed subscription modal on retry")
                    if not self._detect_subscription_wall(driver):
                        return True

                # Still paywalled: track but DON'T apply aggressive backoff
                # Subscription walls can be persistent (days/months)
                # Note: Unlike CAPTCHA, we don't backoff the domain
                logger.info(
                    f"Subscription wall blocking content on {url} - "
                    "this may persist for days/months"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Navigation failed for {url}: {e}")
            return False

    def _simulate_human_reading(self, driver):
        """Simulate realistic human reading and browsing behavior."""
        import random
        import time

        try:
            # Quick processing pause
            time.sleep(0.3)  # Reduced from 1.0-3.0 seconds

            # Get page dimensions for realistic scrolling
            page_height = driver.execute_script("return document.body.scrollHeight")
            viewport_height = driver.execute_script("return window.innerHeight")

            if page_height > viewport_height:
                # Simulate reading pattern: scroll down in chunks
                scroll_positions = []
                current_pos = 0

                while current_pos < page_height:
                    # Random scroll distance (realistic reading chunks)
                    scroll_distance = random.randint(200, 500)
                    current_pos = min(current_pos + scroll_distance, page_height)
                    scroll_positions.append(current_pos)

                # Limit scrolling to avoid timeout - faster scrolling
                for pos in scroll_positions[:3]:  # Reduced from 5 positions
                    driver.execute_script(f"window.scrollTo(0, {pos});")
                    # Quick pause between scrolls
                    time.sleep(0.2)  # Reduced from 0.8-2.0 seconds

                # Scroll back to top (common human behavior)
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.2)  # Reduced from 0.5-1.0 seconds

            # Simulate mouse movement (if ActionChains available)
            if hasattr(driver, "execute_script"):
                # Move mouse to random positions - faster
                for _ in range(1):  # Reduced from 2 iterations
                    x = random.randint(100, 800)
                    y = random.randint(100, 600)
                    driver.execute_script(
                        f"""
                        var event = new MouseEvent('mousemove', {{
                            clientX: {x},
                            clientY: {y}
                        }});
                        document.dispatchEvent(event);
                    """
                    )
                    time.sleep(0.1)  # Reduced from 0.1-0.3 seconds

        except Exception as e:
            logger.debug(f"Human behavior simulation failed: {e}")

    def _try_close_modals(self, driver, url: str) -> bool:
        """Try to close subscription modals and popups.

        Args:
            driver: Selenium WebDriver instance
            url: URL being processed (for logging)

        Returns:
            True if a modal was successfully closed, False otherwise
        """
        try:
            close_selectors = [
                "button[aria-label*='close' i]",  # Case-insensitive close button
                "button[title*='close' i]",
                "button[aria-label*='dismiss' i]",
                "[data-dismiss='modal']",  # Bootstrap modals
                ".modal-close",
                ".close-button",
                ".c-close",
                "button.close",
                "[class*='close'][role='button']",
                # Subscription-specific selectors
                "button[aria-label*='no thanks' i]",
                "button[aria-label*='maybe later' i]",
                "a[href='#'][class*='close']",  # Link-based close buttons
                ".tp-close",  # Piano paywall
                "#close-modal",
            ]

            for selector in close_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements[:2]:  # Try first 2 matches
                        if element.is_displayed() and element.is_enabled():
                            element.click()
                            time.sleep(0.5)
                            logger.info(
                                f"Closed modal on {url} using selector: {selector}"
                            )
                            return True
                except Exception as e:
                    logger.debug(f"Failed to close with {selector}: {e}")
                    continue

            return False

        except Exception as e:
            logger.debug(f"Error closing modals on {url}: {e}")
            return False

    def _detect_subscription_wall(self, driver) -> bool:
        """Detect if page contains a subscription/paywall modal.

        Returns True if subscription wall detected (NOT a bot challenge).
        These should be tracked separately as they may block for days/months.
        """
        try:
            page_source = driver.page_source.lower()

            # Common subscription wall indicators
            subscription_keywords = [
                "subscribe",
                "subscription",
                "subscriber",
                "register to read",
                "sign up to continue",
                "create an account",
                "enter your email",
                "get unlimited access",
                "paywall",
                "premium content",
                "exclusive content",
                "members only",
                "login to continue",
                "register now",
            ]

            # Count keyword matches (need multiple for confidence)
            matches = sum(
                1 for keyword in subscription_keywords if keyword in page_source
            )

            if matches >= 2:  # At least 2 subscription indicators
                logger.info(f"Detected subscription wall ({matches} indicators found)")
                return True

            # Check for common paywall provider elements
            paywall_selectors = [
                "[class*='paywall']",
                "[id*='paywall']",
                "[class*='piano']",  # Piano paywall
                "[id*='piano']",
                "[class*='subscribe-modal']",
                "[id*='subscription']",
                ".registration-wall",
                ".subscriber-wall",
            ]

            for selector in paywall_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements and any(el.is_displayed() for el in elements[:3]):
                        logger.info(f"Detected paywall element: {selector}")
                        return True
                except Exception:
                    continue

            return False

        except Exception as e:
            logger.debug(f"Error in subscription wall detection: {e}")
            return False

    def _try_bypass_challenge(self, driver, url: str) -> bool:
        """
        Attempt to bypass JS-based bot challenges by waiting and clicking.

        Many bot protection systems (Cloudflare, PerimeterX, Akamai) show a
        "checking your browser" or "verifying" page that auto-resolves after
        a few seconds of JavaScript execution. Some require clicking a button.

        This method:
        1. Waits for JavaScript-based challenges to auto-resolve
        2. Looks for and clicks common verification buttons
        3. Waits again to confirm bypass success

        Returns True if the challenge appears to be bypassed.
        """
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            return False

        try:
            logger.info(f"Attempting to bypass challenge on {url}")

            # PHASE 1: Wait for auto-resolving challenges (like Cloudflare)
            # Many JS challenges resolve automatically after fingerprinting
            initial_wait = 5
            logger.debug(f"Waiting {initial_wait}s for challenge to auto-resolve...")
            time.sleep(initial_wait)

            # Check if challenge resolved itself
            if not self._detect_captcha_or_challenge(driver):
                logger.info("Challenge auto-resolved after waiting")
                return True

            # PHASE 2: Look for clickable verification buttons
            # Common button selectors for various bot protection systems
            verification_selectors = [
                # Cloudflare
                "input[type='button'][value*='Verify']",
                "button[type='submit']",
                "#challenge-form button",
                ".cf-turnstile-wrapper button",
                "input[value='Verify you are human']",
                # PerimeterX / Human Security
                "#px-captcha",  # PerimeterX's press-and-hold button
                "button[class*='human']",
                "div[id*='px-captcha']",
                # Generic verification buttons
                "button:contains('Verify')",
                "button:contains('Continue')",
                "button:contains('I am human')",
                "a[class*='verify']",
                "input[value*='Continue']",
                # Akamai Bot Manager
                "#sec-overlay button",
                ".akam-button",
                # DataDome
                "#datadome-modal button",
                # Generic "I'm not a robot" style
                ".g-recaptcha",  # May need to interact with reCAPTCHA iframe
            ]

            for selector in verification_selectors:
                try:
                    # Try CSS selector first
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed() and element.is_enabled():
                            logger.info(f"Found verification element: {selector}")

                            # Move to element with human-like behavior
                            try:
                                actions = ActionChains(driver)
                                # Small random offset for human-like clicking
                                import random

                                offset_x = random.randint(-3, 3)
                                offset_y = random.randint(-3, 3)
                                actions.move_to_element_with_offset(
                                    element, offset_x, offset_y
                                )
                                actions.pause(random.uniform(0.1, 0.3))

                                # Special handling for PerimeterX "Press and Hold"
                                if "px-captcha" in selector or "human" in selector.lower():
                                    logger.info("Detected potential 'Press and Hold' challenge - using long click")
                                    actions.click_and_hold()
                                    actions.pause(random.uniform(4.0, 6.0))
                                    actions.release()
                                else:
                                    actions.click()
                                
                                actions.perform()
                                logger.info(f"Clicked verification element: {selector}")
                            except Exception as click_err:
                                # Fallback to direct click
                                logger.debug(
                                    f"ActionChains failed, trying direct click: {click_err}"
                                )
                                element.click()

                            # Wait for the challenge to process our click
                            time.sleep(3)

                            # Check if we passed
                            if not self._detect_captcha_or_challenge(driver):
                                logger.info(
                                    "Successfully bypassed challenge after clicking"
                                )
                                return True
                            else:
                                logger.debug(
                                    "Challenge still present after clicking, trying next selector"
                                )

                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")
                    continue

            # PHASE 3: Handle PerimeterX press-and-hold challenges
            # These require holding the button for a duration
            try:
                px_button = driver.find_element(By.ID, "px-captcha")
                if px_button.is_displayed():
                    logger.info("Detected PerimeterX press-and-hold challenge")
                    actions = ActionChains(driver)
                    actions.click_and_hold(px_button)
                    # Hold for 8-12 seconds (PerimeterX requires ~10s)
                    import random

                    hold_time = random.uniform(8, 12)
                    logger.debug(f"Holding button for {hold_time:.1f}s")
                    actions.pause(hold_time)
                    actions.release()
                    actions.perform()

                    time.sleep(3)  # Wait for verification

                    if not self._detect_captcha_or_challenge(driver):
                        logger.info(
                            "Successfully bypassed PerimeterX press-and-hold challenge"
                        )
                        return True
            except Exception:
                pass  # No PerimeterX button found

            # PHASE 4: Final wait - some challenges take longer
            logger.debug("Final wait for slow-resolving challenges...")
            time.sleep(5)

            if not self._detect_captcha_or_challenge(driver):
                logger.info("Challenge resolved after final wait")
                return True

            logger.warning(f"Could not bypass challenge on {url}")
            return False

        except Exception as e:
            logger.error(f"Error in challenge bypass attempt: {e}")
            return False

    def _detect_captcha_or_challenge(self, driver) -> bool:
        """Detect if page contains CAPTCHA or other bot challenges.

        Returns True only for actual CAPTCHAs/bot challenges,
        NOT subscription modals.
        """
        try:
            page_source = driver.page_source.lower()

            # 1. Check for actual CAPTCHA elements (high confidence)
            captcha_selectors = [
                "iframe[src*='recaptcha']",  # reCAPTCHA
                "iframe[src*='hcaptcha']",  # hCaptcha
                "[class*='g-recaptcha']",  # reCAPTCHA div
                "[class*='h-captcha']",  # hCaptcha div
                ".cf-challenge-form",  # Cloudflare challenge
                "#challenge-form",  # Generic challenge form
                "form[id*='captcha']",  # CAPTCHA forms
                "#px-captcha",  # PerimeterX
                "div[id*='px-captcha']",  # PerimeterX div
                "iframe[src*='captcha']",  # Generic captcha iframe
            ]

            for selector in captcha_selectors:
                try:
                    if driver.find_elements(By.CSS_SELECTOR, selector):
                        logger.info(f"Detected CAPTCHA element: {selector}")
                        return True
                except Exception:
                    continue

            # 2. Check for bot blocking pages (specific paired patterns)
            # Note: 'verify' and 'challenge' removed - those appear in
            # subscription walls
            bot_block_indicators = [
                ("access denied", "cloudflare"),  # Cloudflare block
                ("checking your browser", "cloudflare"),  # CF checking
                ("just a moment", "cloudflare"),  # CF checking
                ("ray id:", "cloudflare"),  # Cloudflare error page
                ("403 forbidden", "bot"),
                ("403 forbidden", "blocked"),
                ("pardon our interruption", ""),  # PerimeterX
                ("verify you are a human", ""),  # PerimeterX
                ("press and hold", ""),  # PerimeterX
            ]

            for primary, secondary in bot_block_indicators:
                if primary in page_source and secondary in page_source:
                    logger.info(f"Detected bot blocking: {primary} + {secondary}")
                    return True

            # 3. Check for specific CAPTCHA keywords
            # Note: Only CAPTCHA-specific terms, not generic 'challenge'/'verify'
            if any(k in page_source for k in ["recaptcha", "hcaptcha", "perimeterx", "px-captcha"]):
                logger.info("Detected CAPTCHA keyword in page")
                return True

            return False

        except Exception as e:
            logger.debug(f"Error in CAPTCHA detection: {e}")
            return False

    def _is_title_suspicious(self, title: str) -> bool:
        """Detect potentially truncated or malformed titles."""
        if not title:
            return True

        title = title.strip()

        import re

        # Check for obvious truncation patterns
        suspicious_patterns = [
            # Starts with common word endings/fragments (truncated)
            (r"^(peat|ing|ed|ly|tion|ment|ness|ers?|s)\b", re.IGNORECASE),
            # Very short titles (less than 10 chars, too short for news)
            (r"^.{1,9}$", 0),
            # Contains only numbers/punctuation
            (r"^[\d\s\-.,;:!?]+$", 0),
            # Starts with lowercase AND very short (likely truncated)
            # Allow longer lowercase titles (artist names, stylized titles, etc.)
            # NOTE: No IGNORECASE - we want to catch actual lowercase starts
            (r"^[a-z].{0,14}$", 0),
        ]

        for pattern, flags in suspicious_patterns:
            if re.search(pattern, title, flags):
                logger.debug(
                    f"Title flagged as suspicious: '{title}' "
                    f"(matched pattern: {pattern})"
                )
                return True

        return False

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article title."""
        # Try Open Graph title first
        og_title = soup.find("meta", property="og:title")
        if isinstance(og_title, Tag):
            content = og_title.get("content")
            if content:
                return str(content).strip()

        # Try standard title tag
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text().strip()

        # Try h1 as fallback
        h1_tag = soup.find("h1")
        if h1_tag:
            return h1_tag.get_text().strip()

        return None

    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article author."""
        # Try common meta tags
        author_selectors = [
            ("meta", {"name": "author"}),
            ("meta", {"property": "article:author"}),
            ("meta", {"name": "article:author"}),
            ('[rel="author"]', {}),
            (".author", {}),
            (".byline", {}),
        ]

        # local imports kept minimal to avoid heavy startup costs

        for selector, attrs in author_selectors:
            element = soup.find(selector, _ensure_attrs_dict(attrs))
            if isinstance(element, Tag):
                if element.name == "meta":
                    author = element.get("content")
                    if author is not None:
                        author_str = str(author).strip()
                        if author_str:
                            return author_str
                else:
                    author_txt = element.get_text().strip()
                    if author_txt:
                        return author_txt

        return None

    def _update_wire_hints_from_html(
        self, html_text: str | bytes | None, article_url: str | None = None
    ) -> None:
        """Update wire detection hints by inspecting raw HTML."""
        if not html_text:
            return

        if isinstance(html_text, bytes):
            try:
                decoded = html_text.decode("utf-8", errors="ignore")
            except Exception:
                decoded = html_text.decode(errors="ignore")
            html_str = decoded
        else:
            html_str = html_text

        # Extract CMS content metadata (title, author) from JavaScript objects
        self._extract_cms_metadata_from_html(html_str)

        # Try generic structured metadata detection (includes JSON-LD signals)
        structured_hints = self._detect_structured_metadata_wire_from_html(
            html_str, article_url
        )

        # Try Hearst detection (uses window.HRST JavaScript, not JSON-LD)
        hearst_hints = self._detect_hearst_wire_from_html(html_str)

        # Merge all hints (structured metadata takes priority)
        hints = None
        all_hints = [h for h in [structured_hints, hearst_hints] if h]

        for hint in all_hints:
            if hints is None:
                hints = hint
            else:
                hints = self._merge_wire_hints(hints, hint)

        if not hints:
            return

        if not self._latest_wire_hints:
            self._latest_wire_hints = hints
            return

        self._latest_wire_hints = self._merge_wire_hints(self._latest_wire_hints, hints)

    def _extract_cms_metadata_from_html(self, html_text: str) -> None:
        """Extract content metadata from structured data in HTML.

        Captures title, author, description, and publication date from:
        1. JSON-LD structured data (schema.org - most standardized)
        2. OpenGraph and standard meta tags
        3. Generic dataLayer objects (used by many CMSes)
        4. CMS-specific JavaScript patterns (Nexstar, etc.)

        This metadata can fill in gaps when standard extraction fails.
        The method prioritizes standardized formats over CMS-specific ones.
        """
        metadata: Dict[str, Any] = {}

        # =====================================================================
        # 1. JSON-LD structured data (FIRST - most standardized, schema.org)
        # =====================================================================
        if "application/ld+json" in html_text:
            for jsonld_match in _GANNETT_JSONLD_BLOCK_RE.finditer(html_text):
                try:
                    data = json.loads(jsonld_match.group(1))
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        # Skip non-article types
                        item_type = item.get("@type", "")
                        if isinstance(item_type, list):
                            item_type = item_type[0] if item_type else ""
                        # Only process article-like types
                        if item_type and item_type.lower() not in (
                            "newsarticle",
                            "article",
                            "reportagenewsarticle",
                            "webpage",
                            "blogposting",
                            "socialmediaposting",
                        ):
                            continue

                        # Get headline/title
                        if not metadata.get("title"):
                            headline = item.get("headline") or item.get("name")
                            if headline and isinstance(headline, str):
                                metadata["title"] = headline.strip()

                        # Get author (various formats)
                        if not metadata.get("author"):
                            author = item.get("author")
                            author_name = self._extract_author_from_jsonld(author)
                            if author_name:
                                metadata["author"] = author_name

                        # Get datePublished
                        if not metadata.get("publish_date"):
                            pub_date = item.get("datePublished") or item.get(
                                "dateCreated"
                            )
                            if pub_date:
                                metadata["publish_date"] = pub_date

                        # Get description
                        if not metadata.get("description"):
                            desc = item.get("description")
                            if desc and isinstance(desc, str):
                                metadata["description"] = desc.strip()

                        if metadata.get("title") and metadata.get("author"):
                            metadata["cms_source"] = "json_ld"
                            break
                    if metadata.get("title") and metadata.get("author"):
                        break
                except (json.JSONDecodeError, TypeError):
                    continue

        # =====================================================================
        # 2. OpenGraph and standard meta tags
        # =====================================================================
        if not metadata.get("title"):
            # og:title
            og_title_match = re.search(
                r'<meta\s+(?:property|name)=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
                html_text,
                re.IGNORECASE,
            )
            if not og_title_match:
                og_title_match = re.search(
                    r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\']og:title["\']',
                    html_text,
                    re.IGNORECASE,
                )
            if og_title_match:
                metadata["title"] = og_title_match.group(1).strip()
                if not metadata.get("cms_source"):
                    metadata["cms_source"] = "meta_tags"

        if not metadata.get("author"):
            # article:author or author meta tag
            author_match = re.search(
                r'<meta\s+(?:property|name)=["\'](?:article:author|author)["\']\s+content=["\']([^"\']+)["\']',
                html_text,
                re.IGNORECASE,
            )
            if not author_match:
                author_match = re.search(
                    r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\'](?:article:author|author)["\']',
                    html_text,
                    re.IGNORECASE,
                )
            if author_match:
                metadata["author"] = author_match.group(1).strip()
                if not metadata.get("cms_source"):
                    metadata["cms_source"] = "meta_tags"

        if not metadata.get("publish_date"):
            # article:published_time
            pubdate_match = re.search(
                r'<meta\s+(?:property|name)=["\']article:published_time["\']\s+content=["\']([^"\']+)["\']',
                html_text,
                re.IGNORECASE,
            )
            if not pubdate_match:
                pubdate_match = re.search(
                    r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\']article:published_time["\']',
                    html_text,
                    re.IGNORECASE,
                )
            if pubdate_match:
                metadata["publish_date"] = pubdate_match.group(1).strip()

        # =====================================================================
        # 3. Generic dataLayer objects (used by many CMSes for analytics)
        # =====================================================================
        if not metadata.get("title") or not metadata.get("author"):
            # Look for dataLayer.push with article metadata
            # Common fields: articleTitle, articleAuthor, pageTitle, author
            datalayer_matches = re.findall(
                r"dataLayer\.push\s*\(\s*(\{[^}]*\})\s*\)",
                html_text,
                re.IGNORECASE | re.DOTALL,
            )
            for dl_json in datalayer_matches:
                try:
                    data = json.loads(dl_json)
                    if not isinstance(data, dict):
                        continue
                    # Try common title field names
                    if not metadata.get("title"):
                        title = (
                            data.get("articleTitle")
                            or data.get("pageTitle")
                            or data.get("title")
                            or data.get("contentTitle")
                        )
                        if title and isinstance(title, str):
                            metadata["title"] = title.strip()
                            metadata["cms_source"] = "datalayer"
                    # Try common author field names
                    if not metadata.get("author"):
                        author = (
                            data.get("articleAuthor")
                            or data.get("author")
                            or data.get("contentAuthor")
                            or data.get("byline")
                        )
                        if author and isinstance(author, str):
                            metadata["author"] = author.strip()
                            metadata["cms_source"] = "datalayer"
                except (json.JSONDecodeError, TypeError):
                    continue

        # =====================================================================
        # 4. CMS-specific JavaScript patterns (fallback)
        # =====================================================================
        # Nexstar NXSTdata.content pattern
        if not metadata.get("title") or not metadata.get("author"):
            nxst_match = _NXST_CONTENT_RE.search(html_text)
            if nxst_match:
                try:
                    data = json.loads(nxst_match.group(1))
                    if isinstance(data, dict):
                        if not metadata.get("title") and data.get("title"):
                            metadata["title"] = data["title"].strip()
                        if not metadata.get("author") and data.get("authorName"):
                            metadata["author"] = data["authorName"].strip()
                        if not metadata.get("description") and data.get("description"):
                            metadata["description"] = data["description"].strip()
                        if not metadata.get("publish_date") and data.get(
                            "publicationDate"
                        ):
                            metadata["publish_date"] = data["publicationDate"]
                        if not metadata.get("category") and data.get("primaryCategory"):
                            metadata["category"] = data["primaryCategory"]
                        if metadata.get("title") or metadata.get("author"):
                            metadata["cms_source"] = "nexstar"
                except (json.JSONDecodeError, TypeError):
                    pass

        # Generic window.__DATA__ or window.pageData patterns
        if not metadata.get("title") or not metadata.get("author"):
            window_data_match = _WINDOW_DATA_RE.search(html_text)
            if window_data_match:
                try:
                    data = json.loads(window_data_match.group(1))
                    if isinstance(data, dict):
                        # Look for article/content nested objects
                        content = (
                            data.get("article")
                            or data.get("content")
                            or data.get("page")
                            or data
                        )
                        if isinstance(content, dict):
                            if not metadata.get("title"):
                                title = content.get("title") or content.get("headline")
                                if title and isinstance(title, str):
                                    metadata["title"] = title.strip()
                            if not metadata.get("author"):
                                author = (
                                    content.get("author")
                                    or content.get("authorName")
                                    or content.get("byline")
                                )
                                if author and isinstance(author, str):
                                    metadata["author"] = author.strip()
                            if metadata.get("title") or metadata.get("author"):
                                metadata["cms_source"] = "window_data"
                except (json.JSONDecodeError, TypeError):
                    pass

        # Store extracted metadata
        if metadata:
            if self._latest_cms_metadata:
                # Merge, preferring existing values
                for key, value in metadata.items():
                    if (
                        key not in self._latest_cms_metadata
                        or not self._latest_cms_metadata[key]
                    ):
                        self._latest_cms_metadata[key] = value
            else:
                self._latest_cms_metadata = metadata

    def _extract_author_from_jsonld(self, author: Any) -> str | None:
        """Extract author name from JSON-LD author field.

        Handles various formats:
        - String: "John Smith"
        - Object: {"@type": "Person", "name": "John Smith"}
        - Array: [{"@type": "Person", "name": "John Smith"}, ...]
        """
        if isinstance(author, str):
            return author.strip()
        elif isinstance(author, dict):
            name = author.get("name")
            if name and isinstance(name, str):
                return name.strip()
        elif isinstance(author, list) and author:
            # Take first author
            first = author[0]
            if isinstance(first, str):
                return first.strip()
            elif isinstance(first, dict):
                name = first.get("name")
                if name and isinstance(name, str):
                    return name.strip()
        return None

    def _merge_wire_hints(
        self, existing: Dict[str, Any], new_hint: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge wire hint dictionaries while deduplicating services and sources."""
        merged: Dict[str, Any] = dict(existing)

        existing_services = existing.get("wire_services")
        if isinstance(existing_services, list):
            existing_services_list = list(existing_services)
        elif existing_services:
            existing_services_list = [existing_services]
        else:
            existing_services_list = []
        new_services = [svc for svc in (new_hint.get("wire_services") or []) if svc]
        for svc in new_services:
            if svc not in existing_services_list:
                existing_services_list.append(svc)
        if existing_services_list:
            merged["wire_services"] = existing_services_list

        existing_sources = existing.get("raw_source_name")
        if isinstance(existing_sources, list):
            existing_sources_list = list(existing_sources)
        elif existing_sources:
            existing_sources_list = [existing_sources]
        else:
            existing_sources_list = []
        new_source = new_hint.get("raw_source_name")
        if isinstance(new_source, list):
            candidates = [src for src in new_source if src]
        elif new_source:
            candidates = [new_source]
        else:
            candidates = []

        for src in candidates:
            if src not in existing_sources_list:
                existing_sources_list.append(src)
        if existing_sources_list:
            merged["raw_source_name"] = existing_sources_list

        existing_detectors = existing.get("detected_by")
        if isinstance(existing_detectors, list):
            detectors = set(existing_detectors)
        elif existing_detectors:
            detectors = {existing_detectors}
        else:
            detectors = set()

        new_detected_by = new_hint.get("detected_by")
        if isinstance(new_detected_by, list):
            detectors.update(det for det in new_detected_by if det)
        elif new_detected_by:
            detectors.add(new_detected_by)

        if detectors:
            merged["detected_by"] = list(detectors)

        return merged

    def _detect_hearst_wire_from_html(self, html_text: str) -> Dict[str, Any] | None:
        """Detect Hearst inline sourceName assignments for wire identification."""
        if "window.HRST" not in html_text:
            return None

        raw_source: str | None = None

        assignment_match = _HEARST_SOURCE_ASSIGNMENT_RE.search(html_text)
        if assignment_match:
            raw_source = unescape(assignment_match.group(1).strip())
        else:
            for block_match in _HEARST_SOURCE_JSON_BLOCK_RE.finditer(html_text):
                block = block_match.group(1)
                value_match = _HEARST_SOURCE_VALUE_RE.search(block)
                if value_match:
                    raw_source = unescape(value_match.group(1).strip())
                    break

            if not raw_source:
                for value_match in _HEARST_SOURCE_VALUE_RE.finditer(html_text):
                    context_start = max(0, value_match.start() - 200)
                    context_end = min(len(html_text), value_match.end() + 200)
                    context = html_text[context_start:context_end]
                    if "window.HRST" in context:
                        raw_source = unescape(value_match.group(1).strip())
                        break

        if not raw_source:
            return None

        normalized = self._normalize_wire_service_name(raw_source)
        if not normalized:
            return None

        return {
            "detected_by": ["hearst_source_name"],
            "raw_source_name": [raw_source],
            "wire_services": [normalized],
        }

    def _detect_structured_metadata_wire_from_html(
        self, html_text: str, article_url: str | None = None
    ) -> Dict[str, Any] | None:
        """Detect wire content via generic structured metadata signals.

        This method looks for CMS-agnostic metadata patterns that indicate
        syndicated/wire content. These patterns appear across many different
        CMSes (TownNews, Gray TV, Gannett, and others).

        Detection methods (in priority order):
        1. OpenGraph distributor meta tags (article:distributor_category="wires")
        2. Canonical URL pointing to a known wire service domain
        3. JSON-LD signals: author, isBasedOn, mainEntityOfPage, contentSourceCode
        4. dataLayer/CMS syndication fields (tncms.syndication.source, etc.)

        Returns wire hints dict or None if no signals detected.
        """
        detection_methods: list[str] = []
        raw_sources: list[str] = []
        wire_services: list[str] = []
        evidence: list[str] = []

        # 1. Check OpenGraph distributor meta tags
        # Example: <meta property="article:distributor_category" content="wires"/>
        distributor_category = None
        category_match = _META_DISTRIBUTOR_CATEGORY_RE.search(html_text)
        if not category_match:
            category_match = _META_DISTRIBUTOR_CATEGORY_ALT_RE.search(html_text)
        if category_match:
            distributor_category = category_match.group(1).strip().lower()

        distributor_name = None
        name_match = _META_DISTRIBUTOR_NAME_RE.search(html_text)
        if not name_match:
            name_match = _META_DISTRIBUTOR_NAME_ALT_RE.search(html_text)
        if name_match:
            distributor_name = name_match.group(1).strip()

        # If distributor_category indicates wires, this is strong signal
        if distributor_category in ("wires", "wire", "syndicated", "syndication"):
            detection_methods.append("og_distributor_category")
            evidence.append(f"distributor_category={distributor_category}")
            if distributor_name:
                raw_sources.append(distributor_name)
                normalized = self._normalize_wire_service_name(distributor_name)
                if normalized and normalized not in wire_services:
                    wire_services.append(normalized)
                evidence.append(f"distributor_name={distributor_name}")

        # 2. Check canonical URL for cross-domain wire service reference
        canonical_url = None
        canonical_match = _CANONICAL_LINK_RE.search(html_text)
        if not canonical_match:
            canonical_match = _CANONICAL_LINK_ALT_RE.search(html_text)
        if canonical_match:
            canonical_url = canonical_match.group(1).strip()

        if canonical_url:
            try:
                from urllib.parse import urlparse

                canonical_parsed = urlparse(canonical_url)
                canonical_domain = canonical_parsed.netloc.lower()
                # Remove www. prefix
                if canonical_domain.startswith("www."):
                    canonical_domain = canonical_domain[4:]

                # Check if canonical points to a different known wire service domain
                if article_url:
                    article_parsed = urlparse(article_url)
                    article_domain = article_parsed.netloc.lower()
                    if article_domain.startswith("www."):
                        article_domain = article_domain[4:]

                    # If canonical is on a different domain, treat as syndication
                    if canonical_domain != article_domain:
                        # First check if it's a known wire service domain
                        wire_name = None
                        if canonical_domain in _WIRE_SERVICE_DOMAINS:
                            wire_name = _WIRE_SERVICE_DOMAINS[canonical_domain]
                        else:
                            # Check subdomain match (e.g., consumer.healthday.com)
                            for domain, service in _WIRE_SERVICE_DOMAINS.items():
                                if canonical_domain.endswith("." + domain):
                                    wire_name = service
                                    break

                        if wire_name:
                            # Known wire service
                            detection_methods.append("canonical_cross_domain")
                            raw_sources.append(wire_name)
                            evidence.append(f"canonical={canonical_url[:100]}")
                            normalized = self._normalize_wire_service_name(wire_name)
                            if normalized and normalized not in wire_services:
                                wire_services.append(normalized)
                        else:
                            # Unknown domain but cross-domain canonical indicates syndication
                            # (e.g., Hearst TV stations syndicating between each other)
                            detection_methods.append("canonical_cross_domain")
                            raw_sources.append(canonical_domain)
                            evidence.append(
                                f"canonical={canonical_url[:100]} (cross-domain)"
                            )
                            wire_services.append(canonical_domain)
            except Exception:
                pass  # URL parsing failed, continue with other methods

        # 3. Check meta author tag for wire service patterns
        # E.g., <meta name="author" content="Hanna Park, Betsy Klein, CNN"/>
        meta_author = None
        meta_author_match = _META_AUTHOR_RE.search(html_text)
        if not meta_author_match:
            meta_author_match = _META_AUTHOR_ALT_RE.search(html_text)
        if meta_author_match:
            meta_author = meta_author_match.group(1).strip()

        if meta_author:
            wire, _ = self._extract_wire_from_author_string(meta_author)
            if wire and wire not in wire_services:
                detection_methods.append("meta_author")
                raw_sources.append(meta_author)
                wire_services.append(wire)
                evidence.append(f"meta_author={meta_author[:60]}")

        # 4. Check JSON-LD for wire service signals
        # This includes: author field, isBasedOn, mainEntityOfPage, contentSourceCode
        if "application/ld+json" in html_text:
            for block_match in _GANNETT_JSONLD_BLOCK_RE.finditer(html_text):
                try:
                    block_text = block_match.group(1).strip()
                    data = json.loads(block_text)

                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue

                        # Check author field (can be string, dict, or list)
                        author = item.get("author")
                        author_names: list[str] = []

                        if isinstance(author, str):
                            author_names.append(author)
                        elif isinstance(author, dict):
                            name = author.get("name")
                            if isinstance(name, str):
                                author_names.append(name)
                        elif isinstance(author, list):
                            for auth in author:
                                if isinstance(auth, str):
                                    author_names.append(auth)
                                elif isinstance(auth, dict):
                                    name = auth.get("name")
                                    if isinstance(name, str):
                                        author_names.append(name)

                        for author_name in author_names:
                            # First try exact match
                            normalized = self._normalize_wire_service_name(author_name)
                            if normalized and normalized not in wire_services:
                                detection_methods.append("jsonld_author")
                                raw_sources.append(author_name)
                                wire_services.append(normalized)
                                evidence.append(f"author={author_name[:50]}")
                            else:
                                # Try substring match for "Name, Wire Service" patterns
                                wire, _ = self._extract_wire_from_author_string(
                                    author_name
                                )
                                if wire and wire not in wire_services:
                                    detection_methods.append("jsonld_author")
                                    raw_sources.append(author_name)
                                    wire_services.append(wire)
                                    evidence.append(f"author={author_name[:50]}")

                        # Check isBasedOn (republished content from another site)
                        # Used by Gannett/USA Today network sites
                        is_based_on = item.get("isBasedOn", "")
                        if is_based_on:
                            for domain, service in _WIRE_SERVICE_DOMAINS.items():
                                if domain in is_based_on.lower():
                                    detection_methods.append("jsonld_isBasedOn")
                                    evidence.append(f"isBasedOn={is_based_on[:80]}")
                                    normalized = self._normalize_wire_service_name(
                                        service
                                    )
                                    if normalized and normalized not in wire_services:
                                        raw_sources.append(service)
                                        wire_services.append(normalized)
                                    break

                        # Check mainEntityOfPage.@id for cross-domain canonical
                        main_entity = item.get("mainEntityOfPage")
                        if isinstance(main_entity, dict):
                            entity_id = main_entity.get("@id", "")
                            if entity_id:
                                for domain, service in _WIRE_SERVICE_DOMAINS.items():
                                    if domain in entity_id.lower():
                                        detection_methods.append("jsonld_mainEntity")
                                        evidence.append(
                                            f"mainEntityOfPage={entity_id[:80]}"
                                        )
                                        normalized = self._normalize_wire_service_name(
                                            service
                                        )
                                        if (
                                            normalized
                                            and normalized not in wire_services
                                        ):
                                            raw_sources.append(service)
                                            wire_services.append(normalized)
                                        break

                        # Check Gannett-specific contentSourceCode in embedded metadata
                        metadata_str = item.get("metadata", "")
                        if isinstance(metadata_str, str) and metadata_str:
                            try:
                                meta_obj = json.loads(metadata_str)
                                source_code = meta_obj.get("contentSourceCode", "")
                                if source_code == "USAT":
                                    detection_methods.append("jsonld_contentSourceCode")
                                    evidence.append(f"contentSourceCode={source_code}")
                                    normalized = self._normalize_wire_service_name(
                                        "USA Today"
                                    )
                                    if normalized and normalized not in wire_services:
                                        raw_sources.append("USA Today")
                                        wire_services.append(normalized)
                            except (json.JSONDecodeError, TypeError):
                                pass

                except (json.JSONDecodeError, TypeError):
                    continue

        # 4. Check dataLayer/CMS syndication fields
        # tncms.syndication.source, tncms.syndication.origin, townnews.content.source
        syndication_source_match = _DATALAYER_SYNDICATION_SOURCE_RE.search(html_text)
        if syndication_source_match:
            source_value = syndication_source_match.group(1).strip()
            # Syndication source often contains the external source name
            if source_value:
                detection_methods.append("datalayer_syndication")
                raw_sources.append(source_value)
                evidence.append(f"syndication.source={source_value[:50]}")
                normalized = self._normalize_wire_service_name(source_value)
                if normalized and normalized not in wire_services:
                    wire_services.append(normalized)

        syndication_origin_match = _DATALAYER_SYNDICATION_ORIGIN_RE.search(html_text)
        if syndication_origin_match:
            origin_value = syndication_origin_match.group(1).strip()
            if origin_value:
                evidence.append(f"syndication.origin={origin_value[:50]}")
                # Origin URLs can also indicate wire services
                origin_lower = origin_value.lower()
                for domain, service in _WIRE_SERVICE_DOMAINS.items():
                    if domain in origin_lower:
                        detection_methods.append("datalayer_origin")
                        raw_sources.append(service)
                        normalized = self._normalize_wire_service_name(service)
                        if normalized and normalized not in wire_services:
                            wire_services.append(normalized)
                        break

        # Return if any signals were detected
        if not wire_services and not detection_methods:
            return None

        detected_by = (
            detection_methods if detection_methods else ["structured_metadata"]
        )
        return {
            "detected_by": list(set(detected_by)),
            "raw_source_name": list(set(raw_sources)),
            "wire_services": wire_services,
            "evidence": evidence,
        }

    def _get_wire_author_patterns(self) -> list[tuple[str, str, bool]]:
        """Load author patterns from wire_services table with caching.

        Returns list of (pattern, service_name, case_sensitive) tuples.
        """
        import time

        # Check cache (5 minute TTL)
        now = time.time()
        if (
            hasattr(self, "_wire_author_patterns_cache")
            and hasattr(self, "_wire_author_patterns_timestamp")
            and (now - self._wire_author_patterns_timestamp) < 300
        ):
            return self._wire_author_patterns_cache

        try:
            from src.models import WireService
            from src.models.database import DatabaseManager

            db = DatabaseManager()
            with db.get_session() as session:
                patterns = (
                    session.query(
                        WireService.pattern,
                        WireService.service_name,
                        WireService.case_sensitive,
                    )
                    .filter(WireService.active.is_(True))
                    .filter(WireService.pattern_type == "author")
                    .order_by(WireService.priority, WireService.id)
                    .all()
                )
                result = [(p[0], p[1], p[2]) for p in patterns]
                self._wire_author_patterns_cache = result
                self._wire_author_patterns_timestamp = now
                return result
        except Exception:
            # Fallback to empty list if DB unavailable
            return []

    def _match_wire_pattern_in_text(
        self, text: str | None
    ) -> tuple[str | None, str | None]:
        """Match text against DB wire service author patterns.

        Uses regex patterns from wire_services table (pattern_type='author').

        Returns (service_name, matched_pattern) or (None, None).
        """
        if not text:
            return None, None

        patterns = self._get_wire_author_patterns()
        for pattern, service_name, case_sensitive in patterns:
            try:
                flags = 0 if case_sensitive else re.IGNORECASE
                if re.search(pattern, text, flags):
                    return service_name, pattern
            except re.error:
                # Invalid regex pattern, skip it
                continue

        return None, None

    def _normalize_wire_service_name(self, source_name: str | None) -> str | None:
        """Normalize raw source names to canonical wire services.

        First tries exact match against known names, then falls back to
        DB pattern matching for more complex patterns.
        """
        if not source_name:
            return None

        # Quick exact match lookup for common names
        normalized_map = {
            "associated press": "The Associated Press",
            "the associated press": "The Associated Press",
            "ap": "The Associated Press",
            "ap news": "The Associated Press",
            "apnews": "The Associated Press",
            "ap national": "The Associated Press",
            "ap regional": "The Associated Press",
            "reuters": "Reuters",
            "bloomberg": "Bloomberg",
            "bloomberg news": "Bloomberg",
            "agence france-presse": "Agence France-Presse",
            "agence france presse": "Agence France-Presse",
            "afp": "Agence France-Presse",
            "tribune news service": "Tribune News Service",
            "tribune content agency": "Tribune News Service",
            "usa today": "USA Today",
            "usatoday": "USA Today",
            "cnn": "CNN",
            "cnn wire": "CNN",
            "fox news": "Fox News",
            "nbc news": "NBC News",
            "abc news": "ABC News",
            "cbs news": "CBS News",
            "npr": "NPR",
            "pbs": "PBS",
            "upi": "UPI",
            "united press international": "UPI",
            "healthday": "HealthDay",
            "healthday news": "HealthDay",
            "washington post": "Washington Post",
            "the washington post": "Washington Post",
            "new york times": "New York Times",
            "the new york times": "New York Times",
            "los angeles times": "Los Angeles Times",
            "la times": "Los Angeles Times",
            "gray news": "Gray News",
            "states newsroom": "States Newsroom",
            "stacker": "Stacker",
            "talker news": "Talker News",
        }

        lookup_key = source_name.strip().lower()
        exact_match = normalized_map.get(lookup_key)
        if exact_match:
            return exact_match

        # Fall back to DB pattern matching
        service_name, _ = self._match_wire_pattern_in_text(source_name)
        return service_name

    def _extract_wire_from_author_string(
        self, author_str: str | None
    ) -> tuple[str | None, str | None]:
        """Extract wire service from author string using DB patterns.

        Handles patterns like:
        - "TERESA CEROJANO, Associated Press"
        - "Hanna Park, Betsy Klein, CNN"
        - "John Doe | Reuters"

        Returns (service_name, matched_pattern) or (None, None).
        """
        return self._match_wire_pattern_in_text(author_str)

    def _record_publish_date_details(
        self, source: str, details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record metadata about how the publish date was extracted."""
        info = {"source": source}
        if details:
            try:
                info.update(details)
            except Exception:
                # Best-effort merge; fallback to basic info on failure
                info["details_error"] = str(details)
        self._publish_date_details = info

    def _attach_publish_date_fallback_metadata(
        self,
        result: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Copy recorded publish-date details into result metadata."""
        if not isinstance(result, dict) or not self._publish_date_details:
            return

        try:
            details: Dict[str, Any] = deepcopy(self._publish_date_details)
        except Exception:
            details = dict(self._publish_date_details)

        if extra:
            try:
                details.update(extra)
            except Exception:
                details["extra_error"] = str(extra)

        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            result["metadata"] = metadata

        fallbacks = metadata.setdefault("fallbacks", {})
        if isinstance(fallbacks, dict):
            existing = fallbacks.get("publish_date")
            if isinstance(existing, dict):
                try:
                    existing.update(details)
                    details = existing
                except Exception:
                    details["merge_error"] = str(existing)
            fallbacks["publish_date"] = details
        else:
            metadata["fallbacks"] = {"publish_date": details}

        self._publish_date_details = None

    def _merge_publish_date_fallback_metadata(
        self,
        target: Dict[str, Any],
        source: Dict[str, Any],
    ) -> None:
        """Ensure fallback metadata from source is preserved in target."""
        source_metadata = source.get("metadata")
        if not isinstance(source_metadata, dict):
            return

        fallbacks = source_metadata.get("fallbacks")
        if not isinstance(fallbacks, dict):
            return

        fallback_details = fallbacks.get("publish_date")
        if not isinstance(fallback_details, dict):
            return

        try:
            details_copy = deepcopy(fallback_details)
        except Exception:
            details_copy = dict(fallback_details)

        target_metadata = target.get("metadata")
        if not isinstance(target_metadata, dict):
            target_metadata = {}
            target["metadata"] = target_metadata

        target_fallbacks = target_metadata.setdefault("fallbacks", {})

        if isinstance(target_fallbacks, dict):
            existing = target_fallbacks.get("publish_date")
            if isinstance(existing, dict):
                try:
                    existing.update(details_copy)
                    details_copy = existing
                except Exception:
                    details_copy["merge_error"] = str(existing)
            target_fallbacks["publish_date"] = details_copy
        else:
            target_metadata["fallbacks"] = {"publish_date": details_copy}

    def _extract_published_date(self, soup: BeautifulSoup, html: str) -> Optional[str]:
        """Extract publication date using multiple heuristics."""
        self._publish_date_details = None

        # Try JSON-LD first
        try:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    if isinstance(data, list):
                        items = data
                    else:
                        items = [data]

                    for item in items:
                        if not isinstance(item, dict):
                            continue

                        date_published = (
                            item.get("datePublished")
                            or item.get("dateCreated")
                            or item.get("publishedDate")
                        )

                        if date_published:
                            if isinstance(date_published, (list, tuple)):
                                date_published = (
                                    date_published[0] if date_published else None
                                )
                            if isinstance(date_published, dict):
                                date_published = (
                                    date_published.get("@value")
                                    or date_published.get("value")
                                    or str(date_published)
                                )

                            if date_published:
                                try:
                                    parsed_date = dateparser.parse(str(date_published))
                                    return (
                                        parsed_date.isoformat() if parsed_date else None
                                    )
                                except Exception:
                                    self._record_publish_date_details(
                                        "json_ld",
                                        {
                                            "strategy": "script",
                                            "error": "parse_failed",
                                        },
                                    )
                                    continue

                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

        # Try meta tags
        meta_selectors = [
            ("property", "article:published_time"),
            ("name", "pubdate"),
            ("name", "publishdate"),
            ("name", "date"),
            ("itemprop", "datePublished"),
            ("name", "publish_date"),
            ("property", "article:published"),
        ]

        for attr, value in meta_selectors:
            meta_tag = soup.find("meta", attrs={attr: value})
            if meta_tag and isinstance(meta_tag, Tag):
                content = meta_tag.get("content")
                if content:
                    try:
                        parsed_date = dateparser.parse(str(content))
                        if parsed_date:
                            self._record_publish_date_details(
                                "meta_tag",
                                {"attribute": attr, "value": value},
                            )
                            return parsed_date.isoformat()
                        self._record_publish_date_details(
                            "meta_tag",
                            {
                                "attribute": attr,
                                "value": value,
                                "error": "parse_failed",
                            },
                        )
                    except Exception:
                        continue

        # Try time element
        time_tag = soup.find("time")
        if time_tag and isinstance(time_tag, Tag):
            datetime_attr = time_tag.get("datetime")
            if datetime_attr:
                try:
                    parsed_date = dateparser.parse(str(datetime_attr))
                    if parsed_date:
                        self._record_publish_date_details(
                            "time_tag",
                            {"attribute": "datetime"},
                        )
                        return parsed_date.isoformat()
                except Exception:
                    pass

            # Try time text content
            time_text = time_tag.get_text().strip()
            if time_text:
                try:
                    parsed_date = dateparser.parse(time_text)
                    if parsed_date:
                        self._record_publish_date_details(
                            "time_tag",
                            {"attribute": "text"},
                        )
                        return parsed_date.isoformat()
                except Exception:
                    pass

        # Fallback: scan text near bylines or keyworded blocks
        return self._extract_publish_date_from_text_blocks(soup)

    def _extract_content(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract main article content."""
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
            element.decompose()

        # Try common content selectors
        content_selectors = [
            "article",
            '[role="main"]',
            ".article-content",
            ".post-content",
            ".entry-content",
            ".content",
            ".story-body",
            ".article-body",
            "main",
        ]

        for selector in content_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                text = content_element.get_text(separator=" ", strip=True)
                if len(text) > 100:  # Minimum content length
                    return text

        # Fallback to body
        body = soup.find("body")
        if body:
            text = body.get_text(separator=" ", strip=True)
            if len(text) > 100:
                return text

        return None

    def _extract_publish_date_from_text_blocks(
        self, soup: BeautifulSoup
    ) -> Optional[str]:
        """Identify publish date strings near bylines or keyworded text."""
        stripped_strings = [
            s.strip()
            for s in soup.stripped_strings
            if s and s.strip() and len(s.strip()) <= MAX_TEXT_BLOCK_LENGTH
        ]

        if not stripped_strings:
            return None

        seen_candidates: Set[str] = set()

        def try_candidate(
            value: str,
            *,
            strategy: str,
            block_index: int,
            neighbor_index: Optional[int] = None,
        ) -> Optional[str]:
            candidate = " ".join(value.split())
            if not candidate or candidate in seen_candidates:
                return None
            seen_candidates.add(candidate)
            parsed_value = self._parse_publish_date_candidate(candidate)
            if parsed_value:
                details: Dict[str, Any] = {
                    "strategy": strategy,
                    "matched_text": candidate[:160],
                    "block_index": block_index,
                }
                if neighbor_index is not None:
                    details["neighbor_index"] = neighbor_index
                self._record_publish_date_details("text_block", details)
                return parsed_value
            return None

        for idx, text in enumerate(stripped_strings):
            parsed = try_candidate(text, strategy="direct", block_index=idx)
            if parsed:
                return parsed

            if self._contains_publish_keyword(text):
                upper_bound = min(len(stripped_strings), idx + 3)
                for neighbor_idx in range(idx + 1, upper_bound):
                    neighbor = stripped_strings[neighbor_idx]
                    combined = " ".join([text, neighbor])
                    parsed = try_candidate(
                        combined,
                        strategy="keyword_neighbor",
                        block_index=idx,
                        neighbor_index=neighbor_idx,
                    )
                    if parsed:
                        return parsed

            if self._looks_like_byline(text):
                before_start = max(0, idx - 2)
                for neighbor_idx in range(before_start, idx):
                    neighbor = stripped_strings[neighbor_idx]
                    combined = f"{text} {neighbor}"
                    parsed = try_candidate(
                        combined,
                        strategy="byline_combined_before",
                        block_index=idx,
                        neighbor_index=neighbor_idx,
                    )
                    if parsed:
                        return parsed

                after_end = min(len(stripped_strings), idx + 3)
                for neighbor_idx in range(idx + 1, after_end):
                    neighbor = stripped_strings[neighbor_idx]
                    combined = f"{text} {neighbor}"
                    parsed = try_candidate(
                        combined,
                        strategy="byline_combined_after",
                        block_index=idx,
                        neighbor_index=neighbor_idx,
                    )
                    if parsed:
                        return parsed

        loose_parsed = self._extract_publish_date_without_keywords(stripped_strings)
        if loose_parsed:
            return loose_parsed

        return None

    def _parse_publish_date_candidate(self, text: str) -> Optional[str]:
        """Parse an ISO timestamp from a candidate text fragment."""
        if not text:
            return None

        match = PUBLISH_DATE_KEYWORD_REGEX.search(text)
        if not match:
            return None

        tail = text[match.end() :].strip(" |:\u2013-•")
        if not tail:
            return None

        tail = re.split(r"\bby\b", tail, flags=re.IGNORECASE)[0]
        tail = tail.strip(" |:\u2013-•")

        if not tail:
            return None

        try:
            parsed_date = dateparser.parse(tail)
            if parsed_date:
                return parsed_date.isoformat()
        except Exception:
            return None

        return None

    def _contains_publish_keyword(self, text: str) -> bool:
        if not text:
            return False
        return bool(PUBLISH_DATE_KEYWORD_REGEX.search(text))

    def _looks_like_byline(self, text: str) -> bool:
        if not text:
            return False

        stripped = text.strip()
        if not stripped:
            return False

        lower = stripped.lower()
        if lower in {"by", "by:"}:
            return True

        if (
            lower.startswith("by ")
            or lower.startswith("by:")
            or " by " in lower
            or " | by " in lower
            or lower.endswith(" by")
        ):
            return True

        words = [word for word in re.split(r"[\s|,]+", stripped) if word]
        if not words:
            return False

        if any(char.isdigit() for char in stripped):
            return False

        if 1 < len(words) <= 4 and all(
            word[0].isupper() for word in words if word[0].isalpha()
        ):
            return True

        role_keywords = {
            "editor",
            "reporter",
            "writer",
            "correspondent",
            "publisher",
            "staff",
            "photographer",
            "columnist",
            "producer",
        }

        return any(word.lower() in role_keywords for word in words)

    def _looks_like_date_only_line(self, text: str) -> bool:
        if not text:
            return False

        candidate = " ".join(text.split())
        if not candidate or len(candidate) > 80:
            return False

        if self._contains_publish_keyword(candidate):
            return False

        for pattern in DATE_ONLY_REGEX_PATTERNS:
            if pattern.match(candidate):
                return True

        return False

    def _has_byline_context(self, blocks: List[str], index: int) -> bool:
        radius = 4
        start = max(0, index - radius)
        end = min(len(blocks), index + radius + 1)
        for idx in range(start, end):
            if idx == index:
                continue
            neighbor = blocks[idx].strip()
            if not neighbor:
                continue

            lower = neighbor.lower()
            if lower in {"by", "by:"}:
                return True

            if self._looks_like_byline(neighbor):
                return True

        return False

    def _extract_publish_date_without_keywords(
        self, blocks: List[str]
    ) -> Optional[str]:
        if not blocks:
            return None

        search_limit = min(len(blocks), 150)
        for idx in range(search_limit):
            candidate = blocks[idx].strip()
            if not candidate or not self._looks_like_date_only_line(candidate):
                continue

            if idx > 30 and not self._has_byline_context(blocks, idx):
                continue

            try:
                parsed_date = dateparser.parse(candidate)
            except Exception:
                continue

            if not parsed_date:
                continue

            iso_value = parsed_date.isoformat()
            self._record_publish_date_details(
                "text_block_loose",
                {
                    "strategy": "standalone_date",
                    "matched_text": candidate[:160],
                    "block_index": idx,
                },
            )
            return iso_value

        return None

    def _extract_meta_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract meta description."""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if isinstance(meta_desc, Tag):
            content = meta_desc.get("content")
            if content:
                return str(content).strip()

        og_desc = soup.find("meta", property="og:description")
        if isinstance(og_desc, Tag):
            content = og_desc.get("content")
            if content:
                return str(content).strip()

        return None
