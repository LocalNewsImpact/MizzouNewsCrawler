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
from contextlib import contextmanager
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

from src.pipeline.title_repair import repair as repair_split_title
from src.utils.boilerplate import (
    CONSENT,
    MAX_CAPITALIZATION,
    MAX_UTILITY_WORD_RATE,
    MIN_PROSE_DENSITY,
    capitalization_ratio,
    looks_like_article,
    looks_like_paywall,
    prose_density,
    strip_boilerplate,
    strip_furniture,
    utility_word_rate,
)
from src.utils.bot_sensitivity_manager import BotSensitivityManager
from src.utils.comprehensive_telemetry import ExtractionMetrics

from .fingerprint_profile import (
    FingerprintProfile,
    load_fingerprint_profile,
    prepare_user_data_dir,
)
from .proxy_config import ProxyProvider, get_proxy_manager
from .proxy_relay import get_relay_proxy
from .utils import mask_proxy_url

UNBLOCK_MIN_HTML_BYTES = 3000

# Modern browser profile for cloudscraper to bypass Cloudflare bot detection
# Default Firefox 53/Linux profile is flagged as bot - use Chrome/Windows instead
CLOUDSCRAPER_BROWSER_PROFILE = {
    "browser": "chrome",
    "platform": "windows",
    "desktop": True,
}

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

# A canonical URL on a domain OTHER than the article's own is not automatically
# syndication -- it can be the SAME publisher under a second name. Found
# 2026-07-28: emissourian.com's canonical points to missourian.com with an
# IDENTICAL slug, and the page's own TownNews CDN path is
# bloximages.chicago2.vip.townnews.com/missourian.com/shared-content/... --
# missourian.com is this paper's CMS site-key, not a wire source. Two
# hyper-local prep-sports recaps were filed `wire` and excluded from CIN
# classification because of it.
#
# Deliberately NOT raw substring containment. An early draft checked
# `label in domain` and wrongly caught kansascity.com / kansas.com, which is
# real syndication between two different newsrooms in different cities --
# the "match" was coincidental (Kansas City happens to start with the word
# "Kansas"). Real US city/state/country names collide with compound domain
# names constantly, so this only allows an EXACT label match after removing
# one of a short, explicit list of cosmetic affixes, or an identical
# registrable domain (a subdomain variant of the same site).
#
# Validated against all 549 distinct (article_domain, wire_service) pairs
# carrying status='wire' in production on 2026-07-28: suppresses exactly 5,
# all confirmed same-site (emissourian.com/missourian.com, the
# mdcp.nwaonline.com subdomain cluster, kmbc.com/storystudio.kmbc.com), and
# preserves all 544 genuine cross-organization pairs, including
# kansascity.com/kansas.com.
_COSMETIC_DOMAIN_PREFIXES = ("e", "the", "my", "live", "new", "www")


def _registrable_domain(domain: str) -> str:
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def _domain_base_label(domain: str) -> str:
    parts = domain.split(".")
    return parts[-2] if len(parts) >= 2 else domain


def _is_same_site_domain_alias(article_domain: str, canonical_domain: str) -> bool:
    """Whether two cross-domain URLs are plausibly the SAME publisher.

    Two checks, both narrow on purpose:

    1. Identical registrable domain -- a subdomain variant of one site
       (mdcp.nwaonline.com vs nwaonline.com).
    2. The two domains' base labels become EXACTLY equal once one of a short,
       fixed set of cosmetic prefixes is stripped (emissourian -> missourian).
       Never a substring/containment check -- see the module comment above
       for why that specific looser version is unsafe here.
    """
    if _registrable_domain(article_domain) == _registrable_domain(canonical_domain):
        return True

    article_label = _domain_base_label(article_domain)
    canonical_label = _domain_base_label(canonical_domain)
    if article_label == canonical_label:
        return True

    def variants(label: str) -> set[str]:
        out = {label}
        for prefix in _COSMETIC_DOMAIN_PREFIXES:
            if (
                label.startswith(prefix)
                and len(label) - len(prefix) >= 5
                and label[len(prefix) :].isalpha()
            ):
                out.add(label[len(prefix) :])
        return out

    return bool(variants(article_label) & variants(canonical_label))


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


def _mask_proxy_url(url: str | None) -> str:
    """Hide the password in a proxy URL before it reaches a log.

    Proxy URLs became credentialed when Squid moved from IP allowlisting to
    basic auth (the allowlist broke on every GKE autoscale, since each node has
    its own ephemeral egress IP). Several call sites log the URL at INFO, which
    would otherwise write the proxy password into production logs on every
    Selenium escalation.

    ``http://user:secret@host:3128`` -> ``http://user:***@host:3128``
    """
    if not url:
        return ""
    return re.sub(r"://([^:/@]+):([^@]*)@", r"://\1:***@", url)


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

    # Class-level (shared) persistent Chrome driver for reuse across all instances in the pod
    # This prevents multiple Chrome processes from starting when multiple ContentExtractor
    # instances exist in the same process (e.g., during diagnostics)
    _shared_persistent_driver = None
    _shared_driver_creation_count = 0
    _shared_driver_reuse_count = 0
    _shared_driver_reuse_limit = None  # Will be initialized from env var
    # Domains for which the shared driver already holds an authenticated session.
    # Reset whenever the shared driver is recreated (see close_persistent_driver).
    _authenticated_domains: set = set()
    # Domains whose login attempt already failed on this driver. Negatively
    # cached so a broken login isn't retried (each attempt polls ~20-35s) on
    # every subsequent article. Reset with the driver, like the set above.
    _auth_failed_domains: set = set()

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

        # HTML fetched during the current extraction, keyed by the method that
        # fetched it, so the archived copy can be the one that won the content
        self._raw_html_by_method: Dict[str, str] = {}
        self._latest_raw_html: str | None = None
        self._latest_raw_html_method: str | None = None

        # Cache for wire author patterns from DB (5 min TTL)
        self._wire_author_patterns_cache: list[tuple[str, str, bool]] = []
        self._wire_author_patterns_timestamp: float = 0.0

        if self.use_mcmetadata and not MCMETADATA_AVAILABLE:
            logger.warning(
                "mcmetadata requested but package not available; disabling integration"
            )

        # Initialize class-level driver reuse limit from env var (only once)
        if ContentExtractor._shared_driver_reuse_limit is None:
            ContentExtractor._shared_driver_reuse_limit = int(
                os.environ.get("SELENIUM_DRIVER_REUSE_LIMIT", "10")
            )

        # Note: This instance does NOT have its own _persistent_driver anymore.
        # Instead, all instances share ContentExtractor._shared_persistent_driver.
        # This prevents creating multiple Chrome instances when multiple ContentExtractor
        # instances are created in the same pod (e.g., for diagnostics)

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
            ("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"),
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
        # Which RouterProxy backs each domain's current session, so
        # per-request outcomes can be reported back to proxy_router.
        self.domain_router_proxy: dict[str, Any] = {}
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
            f"🔀 Proxy manager initialized with provider: {active_provider.value}"
        )

        # MODIFIED: Use Squid proxy for all proxy traffic
        # All proxy traffic now routes through residential Squid proxy
        squid_proxy_url = os.getenv(
            "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
        )
        logger.info(
            f"All proxy traffic routing through Squid: {_mask_proxy_url(squid_proxy_url)}"
        )

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

        # AMP support cache for tracking domain AMP compatibility
        self._amp_support_cache: Dict[str, Optional[bool]] = {}

        # If fingerprint profile is loaded, use its UA for consistency
        if self._fingerprint_profile and self._fingerprint_profile.user_agent:
            self.current_user_agent = self._fingerprint_profile.user_agent
            logger.info(
                f"Using fingerprint profile UA: {self.current_user_agent[:50]}... "
                "(UA rotation disabled for fingerprint consistency)"
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

        if self._fingerprint_profile:
            logger.info(
                "ContentExtractor initialized with fingerprint profile (UA rotation disabled)"
            )
        else:
            logger.info("ContentExtractor initialized with user agent rotation enabled")

        # Enforce Selenium-first domain when set: block non-browser HTTP sessions
        # to ensure the first network contact for a domain is via headful Selenium.
        # Set `self._enforce_selenium_first_domain` to the domain string during
        # an active Selenium-first attempt; other methods will skip HTTP for that domain.
        self._enforce_selenium_first_domain: str | None = None
        # Diagnostics/override: allow HTTP unblock fallback even if Selenium-first failed.
        # Default disabled; can be enabled via env ALLOW_UNBLOCK_AFTER_SELENIUM_FAIL=true
        try:
            self._allow_unblock_after_selenium_fail = os.getenv(
                "ALLOW_UNBLOCK_AFTER_SELENIUM_FAIL", "false"
            ).lower() in ("1", "true", "yes", "on")
        except Exception:
            self._allow_unblock_after_selenium_fail = False

        # Diagnostics: disable Selenium entirely and use HTTP methods only (for force_all_methods mode)
        try:
            self._disable_selenium_for_diagnostics = os.getenv(
                "DISABLE_SELENIUM_FOR_DIAGNOSTICS", "false"
            ).lower() in ("1", "true", "yes", "on")
        except Exception:
            self._disable_selenium_for_diagnostics = False

    def _create_new_session(self):
        """Create a new session with current user agent and clear cookies."""
        # Initialize cloudscraper session for better Cloudflare handling
        if CLOUDSCRAPER_AVAILABLE and cloudscraper is not None:
            self.session = cloudscraper.create_scraper(
                browser=CLOUDSCRAPER_BROWSER_PROFILE
            )
            logger.info("🔧 Created new cloudscraper session (Chrome/Windows profile)")
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
        logger.info(
            f"🔀 Squid proxy ENFORCED for ALL connections: {_mask_proxy_url(squid_proxy_url)}"
        )

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

        # Enforce Selenium-first if requested for this domain: block HTTP session
        # creation so the browser is the first client to contact the site.
        enforce_domain = getattr(self, "_enforce_selenium_first_domain", None)
        if enforce_domain and enforce_domain == domain:
            logger.info(
                "Selenium-first policy active for %s: blocking non-browser HTTP session until Selenium attempt",
                domain,
            )
            raise Exception(
                f"Selenium-first enforced for {domain}; blocking HTTP session to ensure headful Selenium is first contact"
            )

        # Skip UA rotation if fingerprint profile is loaded (maintain consistency)
        if self._fingerprint_profile and self._fingerprint_profile.user_agent:
            if domain not in self.domain_sessions:
                # Create new session with fingerprint UA. Pass the domain so the
                # session is routed through the shared proxy_router (home vs
                # mizzou Squid) and records which one it picked -- without this
                # the fingerprint path applied a static SQUID_PROXY_URL and never
                # consulted the router, so router selection AND its telemetry
                # (router_proxy) were dead on the primary fetch path.
                new_session = self._create_session_with_fingerprint_ua(domain)
                self.domain_sessions[domain] = new_session
                self.domain_user_agents[domain] = self._fingerprint_profile.user_agent
                self.request_counts[domain] = 0
                logger.debug(
                    f"Created new session for {domain} using fingerprint UA "
                    f"(rotation disabled)"
                )
            return self.domain_sessions[domain]

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
                new_session = cloudscraper.create_scraper(
                    browser=CLOUDSCRAPER_BROWSER_PROFILE
                )
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

            # CRITICAL: ALWAYS use a proxy for ALL connections (domain sessions
            # too) -- never direct. proxy_router picks which Squid (home or
            # Mizzou) based on live per-domain health; get_requests_proxies_
            # for_domain() itself falls back to the always-on home Squid if
            # the router is unavailable or picks something unconfigured, so
            # this can never resolve to no proxy at all.
            router_proxies, router_proxy, _method = (
                self.proxy_manager.get_requests_proxies_for_domain(
                    domain, service="newscrawler"
                )
            )
            self.domain_router_proxy[domain] = router_proxy
            if router_proxies:
                new_session.proxies.update(router_proxies)
                logger.debug(
                    "🔀 Proxy for domain session (%s): %s (%s)",
                    domain,
                    mask_proxy_url(router_proxies.get("http")),
                    router_proxy.value if router_proxy else "unknown",
                )
            else:
                logger.warning(
                    "🚫 No proxy configured for %s (router and Squid fallback "
                    "both unavailable) -- session will attempt direct",
                    domain,
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

    def _create_session_with_fingerprint_ua(self, domain: Optional[str] = None):
        """Create a new session using fingerprint profile user agent.

        When ``domain`` is given, the session's proxy is chosen by the shared
        proxy_router (home vs mizzou Squid, by live per-domain health) and the
        choice is recorded on ``self.domain_router_proxy[domain]`` so it reaches
        per-request telemetry. Falls back to the static SQUID_PROXY_URL only if
        the router (and its own Squid fallback) resolve nothing, so the crawler
        can never end up direct.
        """
        if CLOUDSCRAPER_AVAILABLE and cloudscraper is not None:
            new_session = cloudscraper.create_scraper(
                browser=CLOUDSCRAPER_BROWSER_PROFILE
            )
        else:
            new_session = requests.Session()

        if self._fingerprint_profile and self._fingerprint_profile.user_agent:
            user_agent = self._fingerprint_profile.user_agent
        else:
            user_agent = self.current_user_agent

        # Set headers with fingerprint UA
        headers = {
            "User-Agent": user_agent,
            "Accept": random.choice(self.accept_header_pool),
            "Accept-Language": (
                self._fingerprint_profile.accept_language
                if self._fingerprint_profile
                and self._fingerprint_profile.accept_language
                else random.choice(self.accept_language_pool)
            ),
            "Accept-Encoding": random.choice(self.accept_encoding_pool),
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

        if random.random() > 0.3:
            headers["DNT"] = "1"

        new_session.headers.update(headers)

        # Route through the shared proxy_router when we know the domain, so the
        # home/mizzou choice and its health-based failover apply on the primary
        # fetch path -- and record which proxy was picked for telemetry.
        # get_requests_proxies_for_domain already falls back to the always-on
        # home Squid if the router is unavailable or picks something
        # unconfigured, so router_proxies is None only when even that fails.
        router_proxies = None
        if domain is not None:
            try:
                router_proxies, router_proxy, _method = (
                    self.proxy_manager.get_requests_proxies_for_domain(
                        domain, service="newscrawler"
                    )
                )
                self.domain_router_proxy[domain] = router_proxy
            except Exception as exc:  # never let routing break session creation
                logger.warning(
                    "proxy_router lookup failed for %s (%s); using static Squid",
                    domain,
                    exc,
                )

        if router_proxies:
            new_session.proxies.update(router_proxies)
        else:
            # No domain, or the router resolved nothing: static Squid, never direct.
            squid_proxy_url = os.getenv(
                "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
            )
            new_session.proxies.update(
                {"http": squid_proxy_url, "https": squid_proxy_url}
            )

        return new_session

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

    def _handle_connection_error_with_proxy_escalation(
        self, domain: str, error: Exception
    ) -> None:
        """Handle connection errors (DNS, timeout, network) with proxy escalation.

        When a domain experiences connection errors (DNS failures, timeouts, etc.),
        escalate to try different proxies on retry. This is particularly useful
        for sites experiencing network-level blocking or accessibility issues.

        Args:
            domain: Domain that experienced the connection error
            error: The original exception/error
        """
        error_str = str(error).lower()
        is_connection_error = any(
            indicator in error_str
            for indicator in [
                "connection",
                "timeout",
                "namenotfound",
                "gaierror",
                "getaddrinfo",
                "hostname",
                "unable to resolve",
                "dns",
                "refused",
                "reset by peer",
            ]
        )

        if not is_connection_error:
            return  # Not a connection error, skip escalation

        logger.warning(
            f"🚀 ESCALATION: Connection error for {domain}: {error}. "
            f"Marking for proxy rotation on retry."
        )

        # Mark domain for proxy escalation
        if domain not in self.domain_proxies:
            logger.info(f"Assigning new proxy to {domain} for connection retry")
            self._choose_proxy_for_domain(domain)  # Will pick a new proxy
        else:
            # Force rotation to a different proxy on next retry
            logger.info(f"Rotating proxy for {domain} due to connection error")
            if self.proxy_pool:
                current_proxy = self.domain_proxies.get(domain)
                available = [p for p in self.proxy_pool if p != current_proxy]
                if available:
                    new_proxy = random.choice(available)
                    self.domain_proxies[domain] = new_proxy
                    logger.info(
                        f"Escalated proxy for {domain}: {current_proxy} → {new_proxy}"
                    )

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
                    text("""
                        UPDATE sources
                        SET extraction_method = :method,
                            selenium_only = :is_selenium,
                            bot_protection_type = :protection_type,
                            bot_protection_detected_at = :detected_at
                        WHERE host = :host
                        AND (extraction_method = 'http' OR extraction_method IS NULL)
                    """),
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
                    text("""
                        SELECT COALESCE(extraction_method, 'http'), bot_protection_type
                        FROM sources
                        WHERE host = :host
                    """),
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

    def _get_domain_auth_config(self, host: str) -> Optional[dict]:
        """Return the authenticated-extraction config for a host, or None.

        ``host`` is a normalized bare host (no "www."/port). Matches the sources
        table on host or host_norm, with or without the www. prefix, for a
        publisher that requires login. Result (including negative results) is
        cached in-memory per host.

        Returns a dict with keys: auth_type, auth_secret_name, auth_config
        when the host requires login; otherwise None.
        """
        cache_key = f"auth_config:{host}"
        cache = getattr(self, "_auth_config_cache", None)
        if cache is not None and cache_key in cache:
            return cache[cache_key]

        result: Optional[dict] = None
        try:
            import json as _json

            from sqlalchemy import text

            from src.models.database import DatabaseManager

            db = DatabaseManager()
            with db.get_session() as session:
                row = session.execute(
                    text("""
                        SELECT requires_login, auth_type, auth_secret_name,
                               auth_config
                        FROM sources
                        WHERE host = :host
                           OR host = :www_host
                           OR host_norm = :host
                        """),
                    {"host": host, "www_host": f"www.{host}"},
                ).fetchone()

            if row and row[0]:
                raw_config = row[3]
                if isinstance(raw_config, str):
                    try:
                        raw_config = _json.loads(raw_config)
                    except (ValueError, TypeError):
                        raw_config = {}
                result = {
                    "auth_type": row[1],
                    "auth_secret_name": row[2],
                    "auth_config": raw_config or {},
                }
        except Exception as e:
            logger.error(f"Failed to load auth config for {host}: {e}", exc_info=True)
            result = None

        if not hasattr(self, "_auth_config_cache"):
            self._auth_config_cache = {}
        self._auth_config_cache[cache_key] = result
        return result

    def _ensure_authenticated(self, driver, domain: str) -> None:
        """Ensure the shared driver holds a session for a login-gated domain.

        No-op unless the domain's source record has requires_login set. Performs
        the login at most once per driver lifetime per domain, and does not retry
        a domain whose login already failed on this driver.
        """
        # Normalize to a bare host (drop any userinfo/port and a leading "www.")
        # so a publisher matches whether the article URL uses www. or not and
        # whether the source stores host with or without the prefix.
        host = domain.lower().split("@")[-1].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if (
            host in ContentExtractor._authenticated_domains
            or host in ContentExtractor._auth_failed_domains
        ):
            return

        auth = self._get_domain_auth_config(host)
        if not auth:
            return

        secret_name = auth.get("auth_secret_name")
        try:
            from src.crawler.authenticated_login import (
                perform_login,
                resolve_auth_credentials,
            )

            # Not every mechanism uses a password (SimpleCirc authenticates with
            # an email + billing ZIP), so only the identifier is required here;
            # each mechanism validates the fields it actually needs.
            credentials = resolve_auth_credentials(secret_name)
            if not credentials.get("username") and not credentials.get("account_id"):
                ContentExtractor._auth_failed_domains.add(host)
                logger.warning(
                    "Skipping login for %s: credentials for secret '%s' "
                    "could not be resolved",
                    host,
                    secret_name,
                )
                return

            logger.info("Authenticating to %s before extraction", host)
            ok = perform_login(
                driver,
                auth_type=auth.get("auth_type"),
                auth_config=auth.get("auth_config"),
                credentials=credentials,
            )
            if ok:
                ContentExtractor._authenticated_domains.add(host)
                logger.info("Authenticated session established for %s", host)
            else:
                ContentExtractor._auth_failed_domains.add(host)
                logger.warning(
                    "Login to %s did not confirm; continuing unauthenticated "
                    "(won't retry on this driver)",
                    host,
                )
        except Exception as e:
            ContentExtractor._auth_failed_domains.add(host)
            logger.error(
                "Authentication attempt for %s failed: %s", host, e, exc_info=True
            )

    def _convert_to_amp_url(self, url: str) -> List[str]:
        """Generate AMP URL variations for a given URL.

        Returns list of AMP URLs to try, in priority order:
        1. /amp/ suffix
        2. ?amp=1 parameter
        3. Google AMP Cache format

        Args:
            url: Original article URL

        Returns:
            List of AMP URL candidates to try
        """
        amp_urls = []

        # Pattern 1: /amp/ suffix (most common)
        base_url = url.rstrip("/")
        amp_urls.append(f"{base_url}/amp/")

        # Pattern 2: ?amp=1 query parameter
        separator = "&" if "?" in url else "?"
        amp_urls.append(f"{url}{separator}amp=1")

        # Pattern 3: Google AMP Cache
        # Format: https://domain-com.cdn.ampproject.org/c/s/domain.com/article
        parsed = urlparse(url)
        domain_escaped = parsed.netloc.replace(".", "-")
        path_clean = parsed.path.lstrip("/")
        scheme_prefix = "s" if parsed.scheme == "https" else ""
        amp_cache_url = (
            f"https://{domain_escaped}.cdn.ampproject.org/c/{scheme_prefix}/"
            f"{parsed.netloc}/{path_clean}"
        )
        amp_urls.append(amp_cache_url)

        logger.debug(f"Generated {len(amp_urls)} AMP URL candidates for {url}")
        return amp_urls

    def _validate_amp_page(self, html: str) -> bool:
        """Check if HTML is a valid AMP page.

        Args:
            html: HTML content to validate

        Returns:
            True if page appears to be valid AMP
        """
        if not html or len(html) < 500:
            return False

        # Check for AMP indicators in HTML
        html_lower = html.lower()

        # Check for <html amp> or <html ⚡>
        amp_indicators = [
            "<html amp",
            "<html ⚡",
            "ampproject.org",
            "amp-boilerplate",
            "amp-custom",
        ]

        return any(indicator in html_lower for indicator in amp_indicators)

    def _test_amp_support(self, domain: str, sample_url: Optional[str] = None) -> bool:
        """Test if a domain supports AMP pages.

        Tries to fetch an AMP version of a sample URL to determine if the
        domain supports AMP. Updates the sources table with the result.

        Args:
            domain: Domain to test
            sample_url: Optional specific URL to test (otherwise uses domain homepage)

        Returns:
            True if domain supports AMP
        """
        test_url = sample_url or f"https://{domain}"

        try:
            session = self._get_domain_session(test_url)
            amp_urls = self._convert_to_amp_url(test_url)

            # Try each AMP URL pattern
            for amp_url in amp_urls:
                try:
                    logger.info(f"🔍 Testing AMP support: {amp_url}")
                    response = session.get(amp_url, timeout=self.timeout)

                    if response.status_code == 200:
                        if self._validate_amp_page(response.text):
                            logger.info(
                                f"✅ AMP supported on {domain} (pattern: {amp_url})"
                            )
                            # Update sources table
                            self._mark_domain_amp_supported(domain, True)
                            return True
                        else:
                            logger.debug(f"URL succeeded but not valid AMP: {amp_url}")
                    else:
                        logger.debug(
                            f"AMP URL returned {response.status_code}: {amp_url}"
                        )

                except Exception as e:
                    logger.debug(f"AMP test failed for {amp_url}: {e}")
                    continue

            # No AMP URLs worked
            logger.info(f"❌ AMP not supported on {domain}")
            self._mark_domain_amp_supported(domain, False)
            return False

        except Exception as e:
            logger.warning(f"Failed to test AMP support for {domain}: {e}")
            return False

    def _mark_domain_amp_supported(self, domain: str, supported: bool) -> None:
        """Mark a domain as supporting or not supporting AMP.

        Args:
            domain: Domain to mark
            supported: Whether AMP is supported
        """
        from sqlalchemy import text

        from src.models.database import DatabaseManager

        try:
            db = DatabaseManager()
            with db.get_session() as session:
                session.execute(
                    text("""
                        UPDATE sources
                        SET amp_supported = :supported
                        WHERE host = :host
                    """),
                    {
                        "host": domain,
                        "supported": supported,
                    },
                )
                session.commit()
                logger.info(f"📝 Marked {domain} amp_supported={supported}")
        except Exception as e:
            logger.warning(f"Failed to mark {domain} AMP support: {e}")

    def _get_domain_amp_support(self, domain: str) -> Optional[bool]:
        """Check if a domain is known to support AMP.

        Args:
            domain: Domain to check

        Returns:
            True if known to support AMP, False if known not to support, None if unknown
        """
        # Check in-memory cache first
        cache_key = f"amp_supported:{domain}"
        if cache_key in self._amp_support_cache:
            return self._amp_support_cache[cache_key]

        try:
            from sqlalchemy import text

            from src.models.database import DatabaseManager

            db = DatabaseManager()
            with db.get_session() as session:
                row = session.execute(
                    text("""
                        SELECT amp_supported
                        FROM sources
                        WHERE host = :host
                    """),
                    {"host": domain},
                ).fetchone()

                if row and row[0] is not None:
                    result = bool(row[0])
                    self._amp_support_cache[cache_key] = result
                    return result
                else:
                    return None

        except Exception as e:
            logger.debug(f"Failed to check AMP support for {domain}: {e}")
            return None

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

    def _fetch_amp_html(self, url: str) -> Optional[str]:
        """Attempt to fetch the AMP version of a page."""
        try:
            domain = urlparse(url).netloc
            session = self._get_domain_session(url)

            amp_urls = self._convert_to_amp_url(url)
            if not amp_urls:
                return None

            request_headers = {}
            referer = self._generate_referer(url)
            if referer:
                request_headers["Referer"] = referer

            # Try each AMP URL candidate
            for amp_url in amp_urls:
                try:
                    with self._get_domain_lock(domain):
                        logger.info(f"📡 Fetching AMP URL: {amp_url}")
                        response = session.get(
                            amp_url,
                            timeout=self.timeout,
                            headers=request_headers,
                        )

                    if response.status_code == 200:
                        if self._validate_amp_page(response.text):
                            logger.info(
                                f"✅ Successfully fetched AMP page for {domain}"
                            )

                            # Record success
                            if getattr(self, "bot_sensitivity_manager", None):
                                self.bot_sensitivity_manager.record_bot_detection(
                                    host=domain,
                                    url=url,
                                    event_type="amp_preemptive_success",
                                    http_status_code=200,
                                    response_indicators={"amp_url": amp_url},
                                )
                            return response.text
                        else:
                            logger.debug(
                                f"AMP URL succeeded but not valid AMP: {amp_url}"
                            )
                    else:
                        logger.debug(
                            f"AMP URL returned {response.status_code}: {amp_url}"
                        )

                except Exception as e:
                    logger.debug(f"AMP fetch failed for {amp_url}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error in AMP extraction: {e}")

        return None

    def _create_error_result(
        self, url: str, error_msg: str, metadata: Dict = None
    ) -> Dict[str, Any]:
        """Create a standardized error result."""
        # Record proxy failure for network/bot blocking errors
        is_proxy_failure = any(
            err in error_msg.lower()
            for err in ["bot protection", "cloudflare", "captcha", "403", "429"]
        )
        if is_proxy_failure:
            self.proxy_manager.record_failure()

            domain = urlparse(url).netloc
            router_proxy = self.domain_router_proxy.get(domain)
            self.proxy_manager.report_domain_result(
                domain,
                router_proxy,
                success=False,
                reason=error_msg[:200],
                service="newscrawler",
            )
            self._forget_domain_session(domain)

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

    def _retry_unblock_via_alternate_proxy(
        self,
        url: str,
        domain: Optional[str],
        metrics: Optional["ExtractionMetrics"] = None,
    ) -> Optional[Dict[str, Any]]:
        """Re-run the unblock rung through the other Squid. None if there isn't one.

        Never raises: a second ProxyChallengeError here means both addresses
        were refused, which is the caller's existing "fall through to Selenium"
        case, not a new failure mode to handle.
        """
        if domain is None:
            return None

        # Defensive reads: test doubles built via ContentExtractor.__new__()
        # skip __init__ entirely, so neither attribute is guaranteed. A retry
        # that cannot look up routing is simply not available -- it must not
        # turn a challenge into an AttributeError and abort the extraction.
        router_map = getattr(self, "domain_router_proxy", None)
        proxy_manager = getattr(self, "proxy_manager", None)
        if router_map is None or proxy_manager is None:
            return None

        current = router_map.get(domain)
        if current is None:
            # No recorded choice for this domain, so there is nothing to be the
            # alternate *of*. Same reasoning as the unresolvable-URL case below:
            # a retry we cannot show is going somewhere else is guesswork.
            logger.info(
                "No routed proxy recorded for %s; skipping alternate retry", domain
            )
            return None

        try:
            current_proxies = proxy_manager.get_requests_proxies_for_router_proxy(
                current
            )
            alt_proxies, alt_proxy = proxy_manager.get_alternate_proxies(
                current, current_proxies
            )
        except Exception as exc:  # routing must never break extraction
            logger.warning("alternate-proxy lookup failed for %s: %s", domain, exc)
            return None

        if current_proxies is None:
            # Without the current proxy's URL there is nothing to compare the
            # alternate against, so "different box" cannot be established --
            # and retrying through the address that was just refused costs a
            # request and teaches the router nothing.
            logger.info(
                "Current proxy for %s is unresolvable; skipping alternate retry",
                domain,
            )
            return None

        if not alt_proxies:
            logger.info(
                "No alternate proxy configured; %s stays refused at %s",
                domain,
                getattr(current, "value", current),
            )
            return None

        logger.info(
            "🔁 Retrying %s through %s after a challenge on %s",
            url,
            getattr(alt_proxy, "value", alt_proxy),
            getattr(current, "value", current),
        )
        try:
            result = self._extract_with_unblock_proxy(
                url, None, metrics, domain=domain, proxy_override=alt_proxies
            )
        except ProxyChallengeError as exc:
            logger.info("Alternate proxy also refused %s: %s", url, exc)
            self._report_proxy_outcome(
                domain, alt_proxy, success=False, reason=str(exc)
            )
            return None
        except Exception as exc:  # noqa: BLE001 - retry is best-effort
            logger.warning("Alternate-proxy retry errored for %s: %s", url, exc)
            return None

        if result and result.get("content"):
            self._report_proxy_outcome(domain, alt_proxy, success=True)
            # The alternate worked, so let the next request for this domain
            # re-pick rather than reusing the session built for the refused box.
            self._forget_domain_session(domain)
        return result

    def _report_proxy_outcome(
        self, domain: str, router_proxy, success: bool, reason: Optional[str] = None
    ) -> None:
        """Tell the router how a specific proxy fared, without ever raising."""
        try:
            self.proxy_manager.report_domain_result(
                domain,
                router_proxy,
                success=success,
                reason=(reason or "")[:200] or None,
                service="newscrawler",
            )
        except Exception as exc:  # pragma: no cover - telemetry must not fail a fetch
            logger.debug("report_domain_result failed for %s: %s", domain, exc)

    def _forget_domain_session(self, domain: str) -> None:
        """Drop the cached session for a domain after its proxy was blocked.

        The proxy is chosen once, when the domain's session is built, and then
        baked into ``session.proxies``; every later request for that domain
        reuses the cached session without asking the router again. So when a
        challenge causes the router to back this proxy off for the domain, the
        router has learned and extraction has not -- it keeps sending through
        the refused address until an unrelated user-agent rotation happens to
        rebuild the session.

        Forgetting the session is what makes the router's decision take
        effect: the next request for this domain builds a fresh session and
        calls get_requests_proxies_for_domain() again, which now returns the
        other Squid because the first one is backed off.
        """
        self.domain_sessions.pop(domain, None)
        self.domain_router_proxy.pop(domain, None)
        logger.info(
            "🔁 Dropped cached session for %s so the next request re-picks a proxy",
            domain,
        )

    def clear_all_sessions(self):
        """Clear all domain sessions and reset rotation state."""
        self.domain_sessions.clear()
        self.domain_user_agents.clear()
        self.domain_router_proxy.clear()
        self.request_counts.clear()
        self.last_request_times.clear()
        logger.info("Cleared all domain sessions and rotation state")

    def get_persistent_driver(self):
        """Get or create a persistent Selenium driver for reuse.

        Uses a class-level (shared) driver across all ContentExtractor instances
        in the same process to avoid creating multiple Chrome instances in pods.
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
            ContentExtractor._shared_persistent_driver is not None
            and ContentExtractor._shared_driver_reuse_count
            >= ContentExtractor._shared_driver_reuse_limit
        ):
            logger.info(
                f"Driver reached reuse limit ({ContentExtractor._shared_driver_reuse_limit}), "
                f"recreating to clean up renderer processes"
            )
            self.close_persistent_driver()

        if ContentExtractor._shared_persistent_driver is None:
            logger.info(
                "Creating new persistent ChromeDriver for reuse (shared across all instances)"
            )
            try:
                # Try undetected-chromedriver first (most advanced)
                if can_use_undetected:
                    try:
                        ContentExtractor._shared_persistent_driver = (
                            self._create_undetected_driver(headless=headless_mode)
                        )
                        self._driver_method = "undetected-chromedriver"
                    except Exception as uc_err:
                        logger.warning(
                            f"undetected-chromedriver failed to initialize: {uc_err}; "
                            "falling back to selenium-stealth"
                        )
                        if can_use_stealth:
                            ContentExtractor._shared_persistent_driver = (
                                self._create_stealth_driver(headless=headless_mode)
                            )
                            self._driver_method = "selenium-stealth"
                        else:
                            raise
                elif can_use_stealth:
                    ContentExtractor._shared_persistent_driver = (
                        self._create_stealth_driver(headless=headless_mode)
                    )
                    self._driver_method = "selenium-stealth"
                else:
                    raise Exception("No Selenium implementation available")

                ContentExtractor._shared_driver_creation_count += 1
                logger.info(f"Created persistent driver using {self._driver_method}")

            except Exception as e:
                logger.error(f"Failed to create persistent driver: {e}")
                ContentExtractor._shared_persistent_driver = None
                raise
        else:
            ContentExtractor._shared_driver_reuse_count += 1
            logger.debug(
                f"Reusing persistent driver (reuse count: {ContentExtractor._shared_driver_reuse_count})"
            )

        return ContentExtractor._shared_persistent_driver

    def close_persistent_driver(self):
        """Close the persistent driver and clean up resources."""
        if ContentExtractor._shared_persistent_driver is not None:
            try:
                logger.info(
                    f"Closing persistent driver after "
                    f"{ContentExtractor._shared_driver_reuse_count + 1} uses "
                    f"(created {ContentExtractor._shared_driver_creation_count} times)"
                )
                ContentExtractor._shared_persistent_driver.quit()
            except Exception as e:
                logger.warning(f"Error closing persistent driver: {e}")
            finally:
                ContentExtractor._shared_persistent_driver = None
                ContentExtractor._shared_driver_reuse_count = 0
                # New driver starts with no authenticated sessions and a clean
                # login-failure cache.
                ContentExtractor._authenticated_domains = set()
                ContentExtractor._auth_failed_domains = set()

    def _maybe_import_selenium_cookies(self, driver, domain: str) -> bool:
        """If a cookie file is present, import cookies into the Selenium session.

        Behavior is optional and controlled via environment variables:
        - SELENIUM_IMPORT_COOKIES_FILE: path to JSON cookie file (default: /tmp/selenium_import_cookies.json)
        - SELENIUM_WAIT_FOR_COOKIES: if truthy, wait up to SELENIUM_COOKIE_WAIT_SECS for the file to appear
        - SELENIUM_COOKIE_WAIT_SECS: seconds to wait when SELENIUM_WAIT_FOR_COOKIES is truthy (default: 60)

        Returns True if at least one cookie was applied.
        """
        cookie_file = os.environ.get(
            "SELENIUM_IMPORT_COOKIES_FILE", "/tmp/selenium_import_cookies.json"
        )
        wait_for_file = os.environ.get(
            "SELENIUM_WAIT_FOR_COOKIES", "false"
        ).lower() in (
            "1",
            "true",
            "yes",
        )
        wait_secs = int(os.environ.get("SELENIUM_COOKIE_WAIT_SECS", "60"))

        if not os.path.exists(cookie_file):
            if not wait_for_file:
                logger.debug("No cookie file at %s and wait disabled", cookie_file)
                return False
            # Wait for the file to appear
            start = time.time()
            while (time.time() - start) < wait_secs:
                if os.path.exists(cookie_file):
                    break
                time.sleep(0.5)
        if not os.path.exists(cookie_file):
            logger.debug("Cookie file %s not found after wait", cookie_file)
            return False

        try:
            with open(cookie_file, "r") as f:
                cookie_list = json.load(f)
        except Exception as e:
            logger.warning("Failed to load cookie file %s: %s", cookie_file, e)
            return False

        imported = 0
        try:
            # Prefer CDP Network.setCookie which can set httpOnly and secure cookies
            has_cdp = hasattr(driver, "execute_cdp_cmd")
            if has_cdp:
                try:
                    driver.execute_cdp_cmd("Network.enable", {})
                except Exception:
                    pass

                for c in cookie_list:
                    cookie_domain = c.get("domain") or domain
                    # Accept cookies that match the requested domain (including dot-prefixed domains)
                    if not (
                        cookie_domain == domain
                        or cookie_domain == f".{domain}"
                        or cookie_domain.endswith(domain)
                    ):
                        continue

                    payload = {
                        "name": c.get("name"),
                        "value": c.get("value", ""),
                        "path": c.get("path", "/"),
                        "secure": bool(c.get("secure", False)),
                        "httpOnly": bool(c.get("httpOnly", False)),
                        "domain": cookie_domain,
                        "url": f"https://{domain}{c.get('path', '/')}",
                    }
                    expires = c.get("expires")
                    if isinstance(expires, (int, float)) and expires > 0:
                        payload["expires"] = int(expires)
                    if c.get("sameSite"):
                        payload["sameSite"] = c.get("sameSite")

                    try:
                        driver.execute_cdp_cmd("Network.setCookie", payload)
                        imported += 1
                    except Exception as e:
                        logger.debug(
                            "Network.setCookie failed for %s: %s",
                            payload.get("name"),
                            e,
                        )

            else:
                # Fallback: load domain and use add_cookie (may reveal the challenge page during the load)
                try:
                    driver.set_page_load_timeout(20)
                    driver.get(f"https://{domain}/")
                except Exception:
                    pass  # Domain load may fail if challenge appears; we still try adding cookies

                for c in cookie_list:
                    cookie_domain = c.get("domain") or domain
                    if not (
                        cookie_domain == domain
                        or cookie_domain == f".{domain}"
                        or cookie_domain.endswith(domain)
                    ):
                        continue

                    cookie_payload = {
                        "name": c.get("name"),
                        "value": c.get("value", ""),
                        "path": c.get("path", "/"),
                    }
                    if c.get("secure"):
                        cookie_payload["secure"] = True
                    if c.get("httpOnly"):
                        cookie_payload["httpOnly"] = True
                    if (
                        isinstance(c.get("expires"), (int, float))
                        and c.get("expires") > 0
                    ):
                        cookie_payload["expiry"] = int(c.get("expires"))

                    try:
                        driver.add_cookie(cookie_payload)
                        imported += 1
                    except Exception as e:
                        logger.debug(
                            "driver.add_cookie failed for %s: %s", c.get("name"), e
                        )

            # Record count of imported cookies (names omitted for privacy)
            try:
                rec_path = (
                    f"/tmp/selenium_{domain.replace('.', '_')}_cookies_imported.json"
                )
                with open(rec_path, "w") as rf:
                    json.dump({"imported": imported, "source": cookie_file}, rf)
            except Exception:
                pass

            logger.info(
                "Imported %d cookies for %s from %s", imported, domain, cookie_file
            )
            return imported > 0
        except Exception as e:
            logger.warning("Exception while importing cookies: %s", e)
            return False

    def get_driver_stats(self) -> Dict[str, Any]:
        """Get statistics about driver usage."""
        return {
            "has_persistent_driver": ContentExtractor._shared_persistent_driver
            is not None,
            "driver_creation_count": ContentExtractor._shared_driver_creation_count,
            "driver_reuse_count": ContentExtractor._shared_driver_reuse_count,
            "driver_reuse_limit": ContentExtractor._shared_driver_reuse_limit,
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
        # Allow explicit override via env var
        force_headless = os.getenv("SELENIUM_FORCE_HEADLESS", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if force_headless:
            return True

        if self.selenium_mode == "headful":
            return False

        if self.selenium_mode == "headless":
            return True

        # If headful is requested but no DISPLAY is available (typical in containers),
        # fall back to headless to avoid Chrome startup failures.
        if self.selenium_mode == "headful" and not os.getenv("DISPLAY"):
            logger.warning("No DISPLAY detected; forcing headless Selenium mode")
            return True

        return False

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

        author, author_source = self._extract_author_with_source(soup)
        data = {
            "url": url,
            "title": self._extract_title(soup),
            "author": author,
            # additive key, so existing callers of this public method are
            # unaffected; _parse_with_beautifulsoup reads it to give telemetry
            # visibility into WHICH strategy found the byline (meta tag, CSS
            # selector, or a body-text "By {Name}" pattern) instead of the
            # flat "beautifulsoup" label every field used to share.
            "author_source": author_source,
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
        self._raw_html_by_method = {}
        self._latest_raw_html = None
        self._latest_raw_html_method = None

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

        # ESCALATION STRATEGY: For Cloudflare-protected sites marked as 'selenium',
        # try cloudscraper first before falling back to Selenium. CloudScraper
        # handles Cloudflare JS challenges automatically and is much faster than Selenium.
        skip_http_methods = extraction_method in {"selenium", "unblock"}
        cloudflare_escalation_enabled = (
            extraction_method == "selenium"
            and protection_type == "cloudflare"
            and CLOUDSCRAPER_AVAILABLE
        )
        if cloudflare_escalation_enabled:
            logger.info(
                f"🚀 ESCALATION: {domain} has Cloudflare protection - "
                f"trying cloudscraper before Selenium (faster bypass)"
            )
            skip_http_methods = False  # Allow HTTP methods (cloudscraper) to try first

            # Log the full escalation strategy
            escalation_summary = (
                f"[EXTRACTION ESCALATION] {domain}: "
                f"cloudflare_bypass=cloudscraper, "
                f"proxy_rotation=enabled, "
                f"captcha_backoff=exponential"
            )
            logger.info(escalation_summary)

        # Check for preemptive AMP fetch (allows bypassing Selenium/blocking)
        if not html_for_methods and self._get_domain_amp_support(domain):
            amp_html = self._fetch_amp_html(url)
            if amp_html:
                logger.info(f"⚡️ Preemptively fetched AMP content for {domain}")
                html_for_methods = amp_html
                skip_http_methods = False  # Enable standard parsers on this HTML
                # Mark as handled to avoid expensive Selenium fallback
                if extraction_method == "selenium":
                    logger.info(
                        f"✅ AMP success overrides Selenium requirement for {domain}"
                    )
                    extraction_method = (
                        "http"  # downgrade to http (handled via amp html)
                    )

        selenium_first = self._should_prioritize_selenium(extraction_method)
        selenium_attempted_primary = False

        # DIAGNOSTIC: Skip Selenium if disabled for diagnostics (force_all_methods mode)
        if self._disable_selenium_for_diagnostics:
            logger.info(
                "Selenium disabled for diagnostics; skipping Selenium-first attempt for %s",
                domain,
            )
            selenium_first = False

        if selenium_first and SELENIUM_AVAILABLE:
            reason = (
                "domain_required"
                if extraction_method == "selenium"
                else "headful_primary"
            )
            # Enforce Selenium-first: block HTTP session requests to this domain
            # until Selenium has attempted the first contact. Also ensure the
            # persistent ChromeDriver is created before any possible HTTP calls
            # so the browser is the first network client the site sees.
            self._enforce_selenium_first_domain = domain
            try:
                try:
                    # Create persistent driver proactively (may be a no-op if exists)
                    self.get_persistent_driver()
                    logger.info(
                        "Ensured persistent ChromeDriver created before first contact for %s",
                        domain,
                    )
                except Exception as e:  # Non-fatal: still attempt Selenium extraction
                    logger.warning(
                        "Pre-creation of persistent driver failed for %s: %s",
                        domain,
                        e,
                    )

                attempted, success = self._run_selenium_extraction(
                    url, result, metrics, reason
                )
                selenium_attempted_primary = attempted
                if success and not self._get_missing_fields(result):
                    skip_http_methods = True
                self._apply_cms_metadata_fallback(result)
            finally:
                # Clear enforcement flag regardless of outcome
                self._enforce_selenium_first_domain = None

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

        # ── FETCH ONCE, PARSE MANY ─────────────────────────────────────
        # The single proxied HTTP capture. Every parser below (mcmetadata,
        # newspaper4k, BeautifulSoup) parses THIS html; none of them fetch.
        # A Selenium capture (if selenium-first ran) wins via
        # _capture_for_parsing. With no capture and HTTP allowed, fetch now:
        # NotFound/RateLimit stop extraction; any other failure (bot block,
        # transport error) leaves html None so the Selenium fallback runs.
        html_for_methods = self._capture_for_parsing(html_for_methods)
        if not html_for_methods and not skip_http_methods:
            # Tracked as its own metrics step: the fetch can now fail
            # (404/rate-limit/bot block) before any parser runs, and that
            # outcome must still show up in telemetry.
            if metrics:
                metrics.start_method("http_fetch")
            try:
                html_for_methods = self._fetch_page_html(url, metrics=metrics)
                if metrics:
                    metrics.end_method("http_fetch", True, None, {})
            except (NotFoundError, RateLimitError) as e:
                if metrics:
                    metrics.end_method("http_fetch", False, str(e), {})
                raise
            except Exception as e:
                if metrics:
                    metrics.end_method("http_fetch", False, str(e), {})
                logger.info(f"HTTP capture failed for {url}: {e}; will try Selenium")
                html_for_methods = None

        # Try mcmetadata first if enabled (skip for selenium_only domains).
        # Guarded on html_for_methods so mcmetadata can NEVER be handed a
        # bare URL -- that would trip its vendored self-fetcher (un-proxied,
        # pod-IP egress).
        if self._mcmetadata_enabled() and not skip_http_methods and html_for_methods:
            try:
                logger.info(f"Attempting mcmetadata extraction for {url}")
                if metrics:
                    metrics.start_method("mcmetadata")

                mcmetadata_result = self._parse_with_mcmetadata(
                    url,
                    html_for_methods,
                    include_other_metadata=self.mcmetadata_include_other_metadata,
                )

                if mcmetadata_result:
                    # mcmetadata already knows WHERE the author came from --
                    # structured JSON-LD, a meta tag, or the article body --
                    # and returns it as author_extraction_method. Without this
                    # every mcmetadata field, author included, was stamped
                    # with the flat label "mcmetadata", which is the dominant
                    # success path in production and so left telemetry with
                    # no visibility into byline provenance for the common case.
                    author_method = (mcmetadata_result.get("metadata", {}) or {}).get(
                        "author_extraction_method"
                    )
                    self._merge_extraction_results(
                        result,
                        mcmetadata_result,
                        "mcmetadata",
                        None,
                        metrics,
                        field_methods=(
                            {"author": author_method} if author_method else None
                        ),
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
            and bool(html_for_methods)
        )
        if use_newspaper:
            try:
                logger.info(f"Attempting newspaper4k extraction for {url}")
                if metrics:
                    metrics.start_method("newspaper4k")

                newspaper_result = self._parse_with_newspaper(url, html_for_methods)

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

        # Try BeautifulSoup fallback for missing fields. Parser-only now, so
        # it only runs when we actually have a capture to parse; otherwise
        # the Selenium fallback below is the next step.
        if missing_fields and html_for_methods:
            try:
                logger.info(
                    f"Attempting BeautifulSoup fallback for missing "
                    f"fields {missing_fields} on {url}"
                )
                if metrics:
                    metrics.start_method("beautifulsoup")

                bs_result = self._parse_with_beautifulsoup(url, html_for_methods)

                if bs_result:
                    # Same reasoning as mcmetadata: _extract_author_with_source
                    # tells us whether the byline came from a meta tag, a CSS
                    # byline selector, or a body-text "By {Name}" pattern --
                    # use that instead of the flat "beautifulsoup" label.
                    bs_author_method = (bs_result.get("metadata", {}) or {}).get(
                        "author_extraction_method"
                    )
                    # Only copy missing fields
                    self._merge_extraction_results(
                        result,
                        bs_result,
                        "beautifulsoup",
                        missing_fields,
                        metrics,
                        field_methods=(
                            {"author": bs_author_method} if bs_author_method else None
                        ),
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

        # tls_client is a capture rung between a plain HTTP client and a full
        # browser: the same Squid egress, but a Chrome-like TLS/JA3 fingerprint.
        # It used to run only for domains pre-flagged "unblock", so every other
        # host escalated from a sub-second HTTP capture straight to a Selenium
        # render measured in minutes — skipping the cheap disguise that most
        # often explains the refusal.
        #
        # The flagged case keeps its original semantics, including treating a
        # proxy challenge as terminal. As a general rung it is advisory: a
        # refusal just means this rung failed, and Selenium still gets its turn.
        domain_requires_unblock = extraction_method == "unblock"
        try_tls_capture = bool(missing_fields) and (
            domain_requires_unblock or self._tls_capture_fallback_enabled()
        )

        if try_tls_capture:
            # If Selenium was attempted as the primary method and failed, the default
            # policy skips HTTP unblock fallback because it won't emulate site JS.
            # For diagnostics or incident mitigation, this can be overridden via
            # self._allow_unblock_after_selenium_fail or env ALLOW_UNBLOCK_AFTER_SELENIUM_FAIL.
            skip_after_selenium_failure = selenium_attempted_primary and not getattr(
                self, "_allow_unblock_after_selenium_fail", False
            )
        else:
            skip_after_selenium_failure = False

        if try_tls_capture and skip_after_selenium_failure:
            msg = (
                f"Selenium-first attempt failed for {domain}; "
                "skipping unblock HTTP fetch (won't emulate browser JS)."
            )
            logger.warning(msg)
            if metrics:
                metrics.end_method(
                    "unblock_proxy", False, "selenium_failed_no_fallback", {}
                )
            if domain_requires_unblock:
                raise ProxyChallengeError(
                    f"Proxy challenge/block detected for {url}: selenium_failed_no_fallback"
                )

        if try_tls_capture and not skip_after_selenium_failure:
            try:
                logger.info(
                    f"Attempting unblock proxy extraction for {url} "
                    f"(missing fields: {missing_fields})"
                )
                if metrics:
                    metrics.start_method("unblock_proxy")

                unblock_result = self._extract_with_unblock_proxy(
                    url, None, metrics, domain=domain
                )

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
                logger.warning(f"❌ Proxy challenge for {url}: {e}")
                if metrics:
                    metrics.end_method("unblock_proxy", False, str(e), {})

                # A challenge is a statement about the ADDRESS the request came
                # from, not about the page. Try the other Squid before giving up
                # on HTTP: the same URL routinely returns 200 from the second
                # box. Doing this here matters because the challenge also puts
                # the domain into CAPTCHA backoff, and that backoff then makes
                # _run_selenium_extraction skip the browser -- so without this
                # retry a single block costs the article twice, on the fetch and
                # on the fallback that was supposed to rescue it.
                retry_result = self._retry_unblock_via_alternate_proxy(
                    url, domain, metrics
                )
                if retry_result and retry_result.get("content"):
                    self._merge_extraction_results(
                        result, retry_result, "unblock_proxy", missing_fields, metrics
                    )
                    logger.info(
                        "✅ Unblock proxy succeeded for %s via the alternate proxy",
                        url,
                    )
                    if metrics:
                        metrics.end_method("unblock_proxy", True, None, retry_result)
                elif domain_requires_unblock:
                    # Flagged domains treat a challenge as terminal and mark the
                    # article for retry — Selenium won't help where the site has
                    # already refused this route.
                    raise
                else:
                    # As a general rung this is advisory: the disguise was
                    # refused, which says nothing about whether a real browser
                    # would be. Fall through so Selenium still gets its turn.
                    logger.info(
                        "tls_client capture refused for %s; continuing to Selenium", url
                    )

            except Exception as e:
                logger.error(f"❌ Unblock proxy extraction failed for {url}: {e}")
                if metrics:
                    metrics.end_method("unblock_proxy", False, str(e), {})

        # Re-check missing fields after unblock attempt (ensure CMS metadata applied)
        self._apply_cms_metadata_fallback(result)
        missing_fields = self._get_missing_fields(result)

        # Try Selenium final fallback for remaining missing fields when not already attempted
        if missing_fields and SELENIUM_AVAILABLE and not selenium_attempted_primary:
            if self._selenium_would_add_value(result, missing_fields):
                fallback_reason = (
                    "selenium_secondary" if skip_http_methods else "http_fallback"
                )
                # Why the HTTP capture was rejected -- "empty" / "stub" /
                # "not_article_like". Without this a wall-vs-real-article
                # rejection is indistinguishable in telemetry from an
                # ordinary missing-fields escalation.
                rejection = getattr(self, "_last_capture_rejection", None)
                if rejection:
                    fallback_reason = f"{fallback_reason}:{rejection}"
                    result.setdefault("metadata", {})["capture_rejected_as"] = rejection
                self._run_selenium_extraction(
                    url,
                    result,
                    metrics,
                    fallback_reason,
                    missing_fields=missing_fields,
                )
            else:
                logger.info(
                    "Skipping Selenium for %s: body already captured (%d chars); "
                    "missing %s is not recoverable by a second capture",
                    url,
                    len((result.get("content") or result.get("text") or "").strip()),
                    missing_fields,
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

        # Keep the response fetched by that same method for the raw archive
        self._select_raw_html_for_archive(primary_method)

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
        # REMOVED: Don't prioritize Selenium just because headful mode is enabled
        # Headful mode should only be used when actually needed (for unblock/selenium domains)
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
        field_methods: Optional[Dict[str, str]] = None,
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
            field_methods: Optional per-field override of `method`, for
                sources that know MORE than "which extractor won" -- e.g.
                mcmetadata already tells us whether an author came from
                structured JSON-LD, a meta tag, or the article body
                (`article["authors"]`), but every field it supplied was being
                stamped with the flat label "mcmetadata", discarding that.
                Only overrides fields present in this dict; every other field
                keeps the plain `method` label as before.
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
                target["extraction_methods"][field] = (
                    field_methods.get(field, method) if field_methods else method
                )
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

        # cms_source is a single label for whichever stage (json_ld, meta_tags,
        # datalayer, nexstar, window_data) supplied ANY field first -- it does
        # NOT mean every field came from that stage. A page whose JSON-LD had a
        # title but no author, filled by a later meta-tag stage, stamped BOTH
        # title and author "cms_json_ld": the author's true source (meta_tags)
        # was overwritten by title's. title_source/author_source/
        # publish_date_source are set at the exact point each field is
        # assigned in _extract_cms_metadata_from_html, so they cannot drift
        # this way. cms_source is kept as the fallback for older callers/tests
        # and as a last resort if a per-field source is somehow missing.
        cms_source = cms_meta.get("cms_source", "unknown")

        if not result.get("title") and cms_meta.get("title"):
            result["title"] = cms_meta["title"]
            title_source = cms_meta.get("title_source", cms_source)
            result["extraction_methods"]["title"] = f"cms_{title_source}"
            logger.info(
                "Title filled from CMS metadata (%s): %s",
                title_source,
                cms_meta["title"][:50] if cms_meta["title"] else None,
            )

        if not result.get("author") and cms_meta.get("author"):
            result["author"] = cms_meta["author"]
            author_source = cms_meta.get("author_source", cms_source)
            result["extraction_methods"]["author"] = f"cms_{author_source}"
            logger.info(
                "Author filled from CMS metadata (%s): %s",
                author_source,
                cms_meta["author"],
            )

        if not result.get("publish_date") and cms_meta.get("publish_date"):
            result["publish_date"] = cms_meta["publish_date"]
            publish_date_source = cms_meta.get("publish_date_source", cms_source)
            result["extraction_methods"]["publish_date"] = f"cms_{publish_date_source}"

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

        # Nothing tracked: say so. This used to return "newspaper4k", which
        # invented an attribution for whatever actually ran and silently
        # inflated newspaper4k in every per-method analysis (19 occurrences in
        # a 2h production sample). "unknown" is the honest answer;
        # _select_raw_html_for_archive simply finds no match for it.
        logger.warning("No extraction methods tracked; attribution is unknown")
        return "unknown"

    def _is_extraction_successful(self, result: Dict[str, Any]) -> bool:
        """Check if extraction result contains meaningful content."""
        if not result:
            return False

        # Must have at least title OR content
        title = result.get("title", "").strip()
        content = result.get("content", "").strip()

        return bool(title) or (bool(content) and len(content) > 100)

    def _fetch_page_html(self, url: str, metrics=None) -> str:
        """Fetch page HTML ONCE via the proxied per-domain session.

        This is the crawler's single HTTP capture step -- the ONLY place
        (besides Selenium) that touches a live domain. The parsers
        (mcmetadata, newspaper4k, BeautifulSoup) all parse the string this
        returns; none of them fetch (fetch-once-parse-many). The session
        carries the router-chosen Squid proxy and a rotated browser UA, and
        every outcome is reported back to proxy_router.

        Records per-fetch telemetry on self._last_fetch_proxy_metadata /
        self._last_fetch_http_status for the parsers to attach to results.

        Raises to signal how the caller should proceed:
          - NotFoundError   404/410/permanent-4xx: stop all fallbacks
          - RateLimitError  429/5xx/rate-limited: back off, stop this round
          - Exception       bot protection / transport error: caller should
                            fall through to Selenium
        """
        ttl = getattr(self, "dead_url_ttl", 0)
        if ttl and url in getattr(self, "dead_urls", {}):
            if time.time() < self.dead_urls[url]:
                raise NotFoundError(f"URL is cached dead: {url}")

        domain = urlparse(url).netloc
        http_status = None
        captured_html = None
        self._last_fetch_proxy_metadata = {
            "proxy_used": False,
            "proxy_url": None,
            "proxy_authenticated": False,
            "proxy_status": None,
            "proxy_error": None,
            "router_proxy": None,
        }
        self._last_fetch_http_status = None

        try:
            session = self._get_domain_session(url)
            if self._check_rate_limit(domain):
                raise RateLimitError(f"Domain {domain} is rate limited")

            with self._get_domain_lock(domain):
                logger.info(f"📡 Fetching {url[:80]}... via session for {domain}")

                request_headers = {}
                referer = self._generate_referer(url)
                if referer:
                    request_headers["Referer"] = referer
                    logger.debug(f"Using Referer: {referer}")

                response = None
                amp_supported = self._get_domain_amp_support(domain)
                if amp_supported is True:
                    logger.info(
                        f"🔄 Domain {domain} known to support AMP, trying AMP first"
                    )
                    for amp_url in self._convert_to_amp_url(url):
                        try:
                            logger.info(f"📡 Fetching AMP URL: {amp_url}")
                            response = session.get(
                                amp_url,
                                timeout=self.timeout,
                                headers=request_headers,
                            )
                            if response.status_code == 200 and self._validate_amp_page(
                                response.text
                            ):
                                logger.info(
                                    f"✅ Successfully fetched AMP page for {domain}"
                                )
                                http_status = 200
                                captured_html = response.text
                                self.bot_sensitivity_manager.record_bot_detection(
                                    host=domain,
                                    url=url,
                                    event_type="amp_preemptive_success",
                                    http_status_code=200,
                                    response_indicators={"amp_url": amp_url},
                                )
                                break
                        except Exception as amp_e:
                            logger.debug(
                                f"AMP preemptive fetch failed: {amp_url} - {amp_e}"
                            )
                            continue

                    if not captured_html:
                        logger.warning("AMP preemptive fetch failed, trying normal URL")
                        response = session.get(
                            url, timeout=self.timeout, headers=request_headers
                        )
                else:
                    response = session.get(
                        url, timeout=self.timeout, headers=request_headers
                    )

            http_status = response.status_code
            if metrics is not None:
                # set_http_metrics also derives http_error_type and records
                # size/timing, which the old newspaper fetch supplied.
                # Wrapped: telemetry must never be able to discard a capture
                # we already hold (it did exactly that twice while building
                # this -- a Mock response_time, then a wrong method name).
                try:
                    try:
                        response_ms = float(response.elapsed.total_seconds()) * 1000
                    except (TypeError, ValueError, AttributeError):
                        response_ms = 0.0
                    try:
                        body_size = len(response.text or "")
                    except (TypeError, AttributeError):
                        body_size = 0
                    metrics.set_http_metrics(http_status, body_size, response_ms)
                except Exception as exc:
                    logger.warning("http metrics recording failed: %s", exc)

            session_proxies = getattr(session, "proxies", None)
            session_proxy_url = None
            if isinstance(session_proxies, dict):
                session_proxy_url = session_proxies.get("https") or session_proxies.get(
                    "http"
                )
            if not isinstance(session_proxy_url, str):
                session_proxy_url = None
            router_proxy = self.domain_router_proxy.get(domain)
            fetch_meta: Dict[str, Any] = {
                "proxy_used": bool(session_proxy_url),
                "proxy_url": mask_proxy_url(session_proxy_url),
                "proxy_authenticated": "@" in (session_proxy_url or ""),
                # A status WORD, not the HTTP code. proxy_status_to_int() maps
                # success/failed/bypassed/disabled; handing it the int status
                # raised AttributeError and killed router_proxy on the way
                # through set_proxy_metrics. The HTTP code is already recorded
                # separately by set_http_metrics -> http_status_code.
                "proxy_status": "success" if session_proxy_url else None,
                "proxy_error": None,
                "router_proxy": router_proxy.value if router_proxy else None,
            }
            self._last_fetch_proxy_metadata = fetch_meta

            # Record onto the metrics object HERE, where the fetch actually
            # happened. This dict used to reach telemetry only by way of
            # _parse_with_newspaper's result metadata (the sole reader of
            # _last_fetch_proxy_metadata), so whenever newspaper4k did not run
            # -- the common case, since mcmetadata/http_fetch usually satisfy
            # the required fields first -- proxy_used, proxy_url AND
            # router_proxy were silently dropped. Confirmed live 2026-07-27:
            # 2,621 of 3,150 rows in 6h reported proxy_used=0 and 100% had
            # router_proxy NULL, with a perfect correlation to newspaper4k not
            # running, even though every one of those fetches went through
            # Squid. The proxy was never bypassed; the evidence was.
            # Wrapped so telemetry can never break a capture we already hold.
            if metrics is not None:
                try:
                    metrics.set_proxy_metrics(
                        proxy_used=fetch_meta["proxy_used"],
                        proxy_url=fetch_meta["proxy_url"],
                        proxy_authenticated=fetch_meta["proxy_authenticated"],
                        proxy_status=fetch_meta["proxy_status"],
                        proxy_error=fetch_meta["proxy_error"],
                        router_proxy=fetch_meta["router_proxy"],
                    )
                except Exception as exc:
                    logger.warning("proxy metrics recording failed: %s", exc)

            logger.info(
                f"📥 Received {http_status} for {domain} "
                f"(content: {len(response.text) if response.text else 0} bytes)"
            )

            if captured_html:
                # AMP-preemptive already succeeded above.
                pass
            elif http_status == 429:
                logger.warning(f"Rate limited (429) by {domain}")
                self._handle_rate_limit_error(domain, response)
                self.bot_sensitivity_manager.record_bot_detection(
                    host=domain,
                    url=url,
                    event_type="rate_limit_429",
                    http_status_code=429,
                )
                raise RateLimitError(f"Rate limited (429) by {domain}")
            elif http_status in [401, 403, 502, 503, 504]:
                assert response is not None
                protection_type = self._detect_bot_protection_in_response(response)
                if protection_type:
                    self._record_bot_protection_detection(
                        protection_type=protection_type,
                        status_code=http_status,
                        source="http_fetch",
                    )
                    captured_html = self._try_amp_bypass_for_protection(
                        url, domain, protection_type, response, request_headers
                    )
                    if not captured_html:
                        raise Exception(
                            f"Bot protection on {domain}: "
                            f"{protection_type} ({http_status}) - will try Selenium"
                        )
                else:
                    logger.warning(
                        f"Server error ({http_status}) by {domain} - "
                        f"{response.text[:200] if response.text else 'empty'}"
                    )
                    self._handle_rate_limit_error(domain, response)
                    raise Exception(
                        f"Server error ({http_status}) on {domain} - will try Selenium"
                    )
            elif http_status in (404, 410):
                if ttl:
                    self.dead_urls[url] = time.time() + ttl
                logger.warning(f"Permanent missing ({http_status}) for {url}; caching")
                raise NotFoundError(f"URL returned {http_status}: {url}")
            elif http_status == 200:
                # Take the payload FIRST. Everything after this is
                # bookkeeping, and bookkeeping must never be able to discard
                # a page we already hold -- a Mock response_time in a test
                # once threw inside record_success() and the broad handler
                # below turned a good 200 capture into "capture failed".
                captured_html = response.text
                self._reset_error_count(domain)
                try:
                    self.proxy_manager.record_success(
                        response_time=response.elapsed.total_seconds()
                    )
                    self.proxy_manager.report_domain_result(
                        domain,
                        router_proxy,
                        success=True,
                        service="newscrawler",
                    )
                except Exception as exc:
                    logger.warning("proxy bookkeeping failed for %s: %s", domain, exc)
                ua = self.domain_user_agents.get(domain, "Unknown")
                logger.info(
                    f"✅ Successfully fetched {len(captured_html)} bytes from "
                    f"{domain} (UA: {ua[:30]}...)"
                )
            elif 400 <= http_status < 500:
                logger.warning(f"Client error ({http_status}) for {url}")
                if http_status in (400, 405, 406, 451):
                    if ttl:
                        self.dead_urls[url] = time.time() + ttl
                    raise NotFoundError(f"Client error ({http_status}): {url}")
                raise RateLimitError(f"Client error ({http_status}) on {domain}")
            elif 500 <= http_status < 600:
                logger.warning(f"Server error ({http_status}) on {domain}")
                self._handle_rate_limit_error(domain, response)
                raise RateLimitError(f"Server error ({http_status}) on {domain}")
            else:
                logger.warning(f"Unexpected status {http_status} for {url}")
                raise RateLimitError(f"Unexpected status ({http_status}) on {domain}")

        except (RateLimitError, NotFoundError):
            raise
        except Exception as e:
            # Transport/bot failure. Report it, escalate proxy, and re-raise
            # so the caller falls through to Selenium. Deliberately NO
            # newspaper article.download() fallback here -- that fetched
            # directly from the pod IP, bypassing the proxy.
            self.proxy_manager.report_domain_result(
                domain,
                self.domain_router_proxy.get(domain),
                success=False,
                reason=str(e)[:200],
                service="newscrawler",
            )
            self._handle_connection_error_with_proxy_escalation(domain, e)
            raise

        self._last_fetch_http_status = http_status
        self._update_wire_hints_from_html(captured_html, url)
        self._record_raw_html(captured_html, "http")
        return captured_html

    def _try_amp_bypass_for_protection(
        self, url, domain, protection_type, response, request_headers
    ) -> Optional[str]:
        """AMP-bypass attempt for a bot-protected page. Returns AMP HTML on
        success (PerimeterX only), else None so the caller escalates to
        Selenium. Extracted verbatim from the old newspaper fetch path."""
        if protection_type != "perimeterx":
            is_captcha = self._is_js_required_protection(protection_type)
            if is_captcha:
                self._mark_domain_special_extraction(domain, protection_type)
            self.bot_sensitivity_manager.record_bot_detection(
                host=domain,
                url=url,
                event_type="captcha_detected" if is_captcha else "403_forbidden",
                http_status_code=response.status_code,
                response_indicators={"protection_type": protection_type},
            )
            return None

        logger.info(f"🔄 Attempting AMP bypass for PerimeterX on {domain}")
        session = self._get_domain_session(url)
        for amp_url in self._convert_to_amp_url(url):
            try:
                logger.info(f"📡 Trying AMP URL: {amp_url}")
                amp_response = session.get(
                    amp_url, timeout=self.timeout, headers=request_headers
                )
                if amp_response.status_code == 200 and self._validate_amp_page(
                    amp_response.text
                ):
                    logger.info(f"✅ AMP bypass successful for {domain}!")
                    self._mark_domain_amp_supported(domain, True)
                    self.bot_sensitivity_manager.record_bot_detection(
                        host=domain,
                        url=url,
                        event_type="amp_bypass_success",
                        http_status_code=200,
                        response_indicators={
                            "protection_type": protection_type,
                            "amp_url": amp_url,
                        },
                    )
                    self._reset_error_count(domain)
                    self.proxy_manager.record_success(
                        response_time=amp_response.elapsed.total_seconds()
                    )
                    self.proxy_manager.report_domain_result(
                        domain,
                        self.domain_router_proxy.get(domain),
                        success=True,
                        service="newscrawler",
                    )
                    return amp_response.text
            except Exception as amp_e:
                logger.debug(f"AMP URL failed: {amp_url} - {amp_e}")
                continue

        logger.warning(f"❌ AMP bypass failed for {domain}, trying Selenium")
        self._mark_domain_amp_supported(domain, False)
        self.bot_sensitivity_manager.record_bot_detection(
            host=domain,
            url=url,
            event_type="amp_bypass_failure",
            http_status_code=response.status_code,
            response_indicators={"protection_type": protection_type},
        )
        if self._is_js_required_protection(protection_type):
            self._mark_domain_special_extraction(domain, protection_type)
        return None

    def _parse_with_mcmetadata(
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

        if not html:
            # PARSER-ONLY. Never call mcmetadata.extract(url, html_text=None):
            # that trips its vendored self-fetcher (un-proxied, pod-IP
            # egress). The crawler fetches once via _fetch_page_html and
            # passes html in. No html => nothing to parse.
            raise RuntimeError("mcmetadata requires HTML; none was provided")

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
        self._record_raw_html(raw_html_snapshot, "mcmetadata")

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

        # Reject text that is clearly a cookie consent banner dump rather than article
        # content. Trafilatura (used internally by mcmetadata) can mistake WPConsent /
        # OneTrust cookie description tables for the main body text.
        #
        # This was five literal vendor strings and it failed exactly as a literal
        # list must: kq2.com serves a CLOUDFLARE table, so none of the five
        # matched and 11 of 17 articles in one 4-hour window were stored with
        # 27,372 chars of cookie disclosure as the article body -- all of them
        # CIN-labelled, sitting in the corpus. Adding kq2's wording would have
        # fixed kq2 and missed the next vendor.
        #
        # It now shares the ONE detector in boilerplate.py, which recognises a
        # disclosure table by shape (consent vocabulary saturation plus repeated
        # cookie lifetimes) rather than by vendor. Measured on the 200-row
        # production export: fires on 8/8 of the kq2 dumps and 0 of 180 real
        # stories, which score 0.00 on the consent rate against the table's 3.29.
        #
        # And it is SURGICAL. The old guard set text_content = None, so one
        # marker anywhere discarded the whole capture -- a page carrying a banner
        # AND a story lost the story too. strip_furniture removes the table and
        # returns the rest, so a real article below a banner survives intact.
        if text_content:
            stripped = strip_furniture(text_content)
            if CONSENT in stripped.kinds:
                if stripped.text:
                    logger.warning(
                        "mcmetadata returned a consent-banner table for %s; "
                        "excised it and kept %d chars of article text",
                        url,
                        len(stripped.text),
                    )
                    text_content = stripped.text
                else:
                    logger.warning(
                        "mcmetadata returned consent-banner text for %s; discarding "
                        "content so downstream extractors can provide it",
                        url,
                    )
                    text_content = None

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

    def _parse_with_newspaper(self, url: str, html: str = None) -> Dict[str, Any]:
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
        proxy_metadata: Dict[str, Any] = {
            "proxy_used": False,
            "proxy_url": None,
            "proxy_authenticated": False,
            "proxy_status": None,
            "proxy_error": None,
            "router_proxy": None,
        }

        if not html:
            # Parser-only: mcmetadata / newspaper4k / BeautifulSoup never
            # fetch. The crawler fetches once (_fetch_page_html) and passes
            # the HTML in. Being called without html means the fetch failed
            # upstream and this parser has nothing to do.
            return self._create_error_result(
                url, "newspaper4k called without html", {"status": None}
            )

        article.html = html
        proxy_metadata = dict(
            getattr(self, "_last_fetch_proxy_metadata", None) or proxy_metadata
        )
        http_status = getattr(self, "_last_fetch_http_status", None)

        article.parse()

        # Extract publish date if available
        publish_date = None
        if hasattr(article, "publish_date") and article.publish_date:
            publish_date = article.publish_date.isoformat()

        self._update_wire_hints_from_html(getattr(article, "html", None), url)
        self._record_raw_html(getattr(article, "html", None), "newspaper4k")

        return {
            "url": url,
            # newspaper4k splits a title on a bare hyphen and keeps the
            # longer half, so "Van-Far girls widen gap" is stored as "Far
            # girls widen gap". Put the cut half back where the page's own
            # markup proves it was there (src/pipeline/title_repair.py).
            "title": repair_split_title(article.title, html),
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

    def _parse_with_beautifulsoup(self, url: str, html: str = None) -> Dict[str, Any]:
        """Extract content using BeautifulSoup with bot-avoidance."""
        page_html = html
        if page_html is None:
            # Parser-only: BeautifulSoup never fetches. The crawler
            # fetches once (_fetch_page_html) and passes the HTML in.
            return {}

        self._update_wire_hints_from_html(page_html, url)
        self._record_raw_html(page_html, "beautifulsoup")

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
                "author_extraction_method": raw.get("author_source"),
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
        domain: Optional[str] = None,
        proxy_override: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Extract content using Squid proxy for strong bot protection.

        Routes requests through residential Squid proxy to bypass
        PerimeterX, DataDome, and other enterprise bot protections.

        Args:
            url: URL to extract
            domain: When given, the proxy is chosen by the shared proxy_router
                (home vs mizzou Squid, by live per-domain health) instead of
                the static SQUID_PROXY_URL -- this was the one fetch rung that
                still bypassed the router after #416/d30ee7f0 fixed the
                primary session path; every unblock-proxy challenge always
                landed on home Squid because mizzou Squid was never tried.

        Returns:
            Extraction result dict with title, author, content, etc.
        """
        try:
            import warnings

            warnings.filterwarnings("ignore", message="Unverified HTTPS request")

            # Route through the shared proxy_router when we know the domain, so
            # the home/mizzou choice and its health-based failover apply here
            # too. get_requests_proxies_for_domain already falls back to the
            # always-on home Squid if the router is unavailable or picks
            # something unconfigured, so this can never end up direct.
            router_proxies = None
            router_proxy = None
            if proxy_override:
                # A caller retrying after a challenge already knows which box
                # to use; asking the router again would just return the one
                # that was refused, since backoff is not instantaneous.
                router_proxies = proxy_override
            elif domain is not None:
                try:
                    router_proxies, router_proxy, _method = (
                        self.proxy_manager.get_requests_proxies_for_domain(
                            domain, service="newscrawler"
                        )
                    )
                    self.domain_router_proxy[domain] = router_proxy
                except Exception as exc:  # never let routing break extraction
                    logger.warning(
                        "proxy_router lookup failed for %s (%s); using static Squid",
                        domain,
                        exc,
                    )

            # Both branches must end with a real URL string. A truthy
            # router_proxies dict that happens to carry neither "http" nor
            # "https" would otherwise leave this None, and requests treats
            # proxies={"http": None} as NO PROXY -- egressing the pod IP, the
            # exact leak the Squid requirement exists to prevent. mypy caught
            # it as `Any | None` where `str` was expected.
            squid_proxy_url = None
            if router_proxies:
                squid_proxy_url = router_proxies.get("http") or router_proxies.get(
                    "https"
                )
            if not squid_proxy_url:
                squid_proxy_url = os.getenv(
                    "SQUID_PROXY_URL", "http://t9880447.eero.online:3128"
                )

            logger.info(
                f"Using Squid proxy for unblock extraction: {_mask_proxy_url(squid_proxy_url)}"
            )

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

            logger.info(
                f"Fetching {url} via Squid proxy at {_mask_proxy_url(squid_proxy_url)}"
            )

            # Simple request through Squid proxy
            try:
                # Prefer tls_client (if available) to mimic Chrome-like TLS/HTTP2 fingerprints when making
                # unblock proxy requests. Fall back to requests if tls_client is not installed or fails.
                response = None
                status_code = None
                html = ""
                try:
                    import tls_client  # optional dependency; provides chrome-like TLS fingerprints

                    logger.info(
                        "Using tls_client for unblock extraction (Chrome-like TLS fingerprint)"
                    )
                    session = tls_client.Session(
                        client_identifier="chrome_143", random_tls_extension_order=False
                    )
                    # tls_client is NOT requests-compatible: its execute_request
                    # signature is (..., insecure_skip_verify, timeout_seconds,
                    # proxy). Calling it with requests' names — proxies=/timeout=/
                    # verify= — raises TypeError on the first one, so this rung
                    # never actually ran and every request quietly fell through
                    # to plain `requests`, losing the Chrome TLS fingerprint that
                    # is the whole point of the rung.
                    tls_resp = session.get(
                        url,
                        headers=headers,
                        proxy=proxy_url,
                        timeout_seconds=30,
                        insecure_skip_verify=True,
                    )
                    response = tls_resp
                except ImportError as exc:
                    # Genuinely optional: not installed in this image.
                    logger.info(
                        "tls_client not installed (%s); falling back to requests",
                        exc,
                    )
                except Exception as exc:  # pragma: no cover - defensive fallback
                    # Installed but the call failed. Louder than ImportError on
                    # purpose: the fallback still returns a page, so this degrades
                    # silently and the capture rung disappears without anything
                    # failing. That is exactly how the signature drift above went
                    # unnoticed for 28 occurrences in a single sweep.
                    logger.warning(
                        "tls_client request failed (%s: %s); falling back to requests "
                        "— the Chrome TLS fingerprint is NOT in effect for %s",
                        type(exc).__name__,
                        exc,
                        url,
                    )

                if response is None:
                    response = requests.get(
                        url,
                        headers=headers,
                        proxies={"http": proxy_url, "https": proxy_url},
                        verify=False,
                        timeout=30,
                    )

                # Normalize response properties for both tls_client and requests
                try:
                    html = response.text
                except Exception:
                    html = getattr(response, "content", b"").decode(
                        "utf-8", errors="replace"
                    )
                status_code = getattr(response, "status_code", None)
                html_len = len(html)
                self._record_raw_html(html, "unblock_proxy")

                # Record proxy telemetry HERE. This capture path never touches
                # _fetch_page_html, which until now was the only place
                # set_proxy_metrics() was called -- so every extraction captured
                # by this rung reported proxy_used=0, proxy_url NULL and
                # router_proxy NULL despite going through Squid. Measured
                # 2026-07-28 on 250 rows: all 47 with router_proxy NULL were
                # captured by this path or by Selenium, never by http_fetch.
                # Same defect class as the one fixed on the fetch path: the
                # proxy was never bypassed, only the evidence was lost.
                if metrics is not None:
                    try:
                        router_choice = (
                            self.domain_router_proxy.get(domain) if domain else None
                        )
                        metrics.set_proxy_metrics(
                            proxy_used=bool(proxy_url),
                            proxy_url=mask_proxy_url(proxy_url),
                            proxy_authenticated="@" in (proxy_url or ""),
                            proxy_status="success" if proxy_url else None,
                            proxy_error=None,
                            router_proxy=(
                                router_choice.value if router_choice else None
                            ),
                        )
                    except Exception as exc:
                        logger.warning(
                            "unblock proxy metrics recording failed: %s", exc
                        )

                logger.info(
                    f"Squid proxy returned {html_len} bytes for {url} (status: {status_code})"
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
                if (status_code is not None and status_code >= 400) or html_len < 1000:
                    logger.warning(
                        f"Squid proxy returned small/failed response for {url} (len={html_len}, status={status_code})"
                    )
                    raise ProxyChallengeError(
                        f"Proxy challenge/block detected for {url}: status_{status_code}"
                    )

                # Check for suspiciously short responses (often challenge pages)
                if html_len < 500 and status_code in [403, 503]:
                    logger.warning(
                        f"Suspicious short response for {url} (len={html_len}, status={status_code})"
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
                    "title": repair_split_title(article.title, html) or "",
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
                if domain is not None:
                    self.proxy_manager.report_domain_result(
                        domain, router_proxy, success=True, service="newscrawler"
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
            if domain is not None:
                self.proxy_manager.report_domain_result(
                    domain,
                    router_proxy,
                    success=False,
                    reason=str(e)[:200],
                    service="newscrawler",
                )
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

            # For subscriber/paywalled publishers, establish an authenticated
            # session on the driver (once per driver lifetime) before navigating
            # so the session cookies carry through to the article fetch.
            try:
                self._ensure_authenticated(driver, urlparse(url).netloc)
            except Exception as auth_err:
                logger.warning("Authentication hook error for %s: %s", url, auth_err)

            # Navigate with human-like behavior
            success = self._navigate_with_human_behavior(driver, url)
            if not success:
                return {}

            # Extract content after ensuring page is loaded
            # Stop the page load BEFORE reading page_source. Reading it while
            # the document is still fetching ads and trackers blocks until the
            # load settles — measured at ~208s on newstribune, versus 0.1s when
            # the stop runs first (nav itself is ~2s).
            #
            # The stop used to run immediately after this read, with a comment
            # noting it "fixes 147s timeout issue" — the right instinct applied
            # one line too late, since page_source is what blocks.
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass  # Ignore if page already finished loading

            with self._phase("extract_page_source"):
                html = driver.page_source

            self._update_wire_hints_from_html(html, url)
            self._record_raw_html(html, "selenium")

            soup = BeautifulSoup(html, "html.parser")

            author, author_source = self._extract_author_with_source(soup)
            result: Dict[str, Any] = {
                "url": url,
                "title": self._extract_title(soup),
                "author": author,
                "publish_date": self._extract_published_date(soup, html),
                "content": self._extract_content(soup),
                "metadata": {
                    "meta_description": self._extract_meta_description(soup),
                    "extraction_method": "selenium",
                    # Which of the three strategies found the byline (meta
                    # tag, CSS selector, body-text pattern), not just the flat
                    # "selenium" label every field on this path used to share.
                    "author_extraction_method": author_source,
                    "stealth_mode": True,
                    "stealth_method": stealth_method,
                    "page_source_length": len(html),
                    "driver_reused": ContentExtractor._shared_driver_reuse_count > 0,
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

    @staticmethod
    def _resolve_selenium_proxy() -> str:
        """The proxy Selenium egresses through.

        Defined once so telemetry cannot report a different value than the
        driver actually uses -- the three driver-creation sites each inline
        this same lookup, and a divergence between them would be invisible.
        """
        return os.getenv(
            "SELENIUM_PROXY",
            os.getenv("SQUID_PROXY_URL", "http://t9880447.eero.online:3128"),
        )

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
            # A Selenium capture skips _fetch_page_html entirely, which was the
            # only caller of set_proxy_metrics -- so every Selenium-captured
            # extraction reported proxy_used=0 with a NULL proxy_url even
            # though Chrome egresses through the auth relay to Squid. That
            # under-reporting was invisible while Selenium was broken (it
            # produced no rows at all from 2026-07-25 to 07-27) and appeared
            # the moment it started working again: 2026-07-28, all 47 of 250
            # rows missing proxy data were Selenium- or unblock-captured.
            #
            # router_proxy stays None deliberately: Selenium reads a static
            # SELENIUM_PROXY and never calls get_requests_proxies_for_domain(),
            # so no router decision exists to record. That is a real gap in
            # #413's home-vs-mizzou failover -- browser traffic is exempt from
            # it -- but it is a behaviour change, not a telemetry one, so it is
            # recorded honestly here rather than papered over with a guess.
            try:
                selenium_proxy = self._resolve_selenium_proxy()
                metrics.set_proxy_metrics(
                    proxy_used=bool(selenium_proxy),
                    proxy_url=mask_proxy_url(selenium_proxy),
                    proxy_authenticated="@" in (selenium_proxy or ""),
                    proxy_status="success" if selenium_proxy else None,
                    proxy_error=None,
                    router_proxy=None,
                )
            except Exception as exc:
                logger.warning("selenium proxy metrics recording failed: %s", exc)

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

            # Selenium is a CAPTURE mechanism, not an extractor: it renders
            # HTML that the real parsers can read. Until now only its own
            # generic soup extraction read that render, so after paying for a
            # browser we took the weaker parser on the better capture —
            # trafilatura never saw the rendered page on this path at all.
            #
            # So parse the capture properly first. Whatever trafilatura leaves
            # missing, Selenium's own result fills below.
            capture = self._raw_html_by_method.get("selenium")
            if capture and self._mcmetadata_enabled():
                # Fields carried over from a bot-blocked HTTP attempt are
                # probably challenge-page text, so let a real parse of the
                # rendered page replace them. Otherwise only fill gaps.
                http_attempt_suspect = bool(
                    self._last_bot_protection_detection
                    or result.get("_bot_protection_detected")
                )
                try:
                    capture_result = self._parse_with_mcmetadata(url, capture)
                    if capture_result:
                        # Same reasoning as the primary mcmetadata call: use
                        # mcmetadata's own author_extraction_method instead of
                        # the flat "mcmetadata" label, so telemetry can tell a
                        # structured (JSON-LD / meta tag) byline apart from one
                        # found in the rendered page's body.
                        author_method = (capture_result.get("metadata", {}) or {}).get(
                            "author_extraction_method"
                        )
                        self._merge_extraction_results(
                            result,
                            capture_result,
                            "mcmetadata",
                            metrics=metrics,
                            allow_overwrite=http_attempt_suspect,
                            field_methods=(
                                {"author": author_method} if author_method else None
                            ),
                        )
                        logger.info(
                            "Parsed the Selenium capture with mcmetadata for %s", url
                        )
                except Exception as exc:  # pragma: no cover - parser variety
                    logger.info(
                        "mcmetadata could not parse the Selenium capture for %s: %s",
                        url,
                        exc,
                    )

            if selenium_result and selenium_result.get("content"):
                # Selenium's own soup extraction is the LAST resort, so it
                # fills only what is still missing after the capture was
                # parsed properly above.
                #
                # This used to merge with allow_overwrite=True across
                # title/author/content/metadata regardless of what Selenium had
                # been called for, so an escalation over a missing byline threw
                # away body text a better parser had produced — and would now
                # immediately undo the trafilatura parse of its own capture.
                # It also made telemetry credit Selenium for fields it had
                # merely overwritten.
                still_missing = self._get_missing_fields(result)
                # Same reasoning as the mcmetadata/beautifulsoup merges above:
                # _extract_author_with_source tells us whether the byline came
                # from a meta tag, a CSS byline selector, or a body-text
                # pattern -- use that instead of the flat "selenium" label.
                selenium_author_method = (
                    selenium_result.get("metadata", {}) or {}
                ).get("author_extraction_method")
                self._merge_extraction_results(
                    result,
                    selenium_result,
                    "selenium",
                    fields_to_copy=still_missing,
                    metrics=metrics,
                    allow_overwrite=False,
                    field_methods=(
                        {"author": selenium_author_method}
                        if selenium_author_method
                        else None
                    ),
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

        # Prefer the consolidated helper which implements cross-CDP fallbacks
        if profile.user_agent:
            try:
                self._set_user_agent_override(driver, profile.user_agent)
            except Exception as exc:
                logger.debug("CDP UA override failed in helper: %s", exc)

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

            # Also apply it to the CURRENT document. addScriptToEvaluateOnNewDocument
            # only fires on subsequent navigations, so without this the page the
            # driver is already sitting on keeps the container's real values --
            # and any detector reading them before the first navigation sees
            # straight through the profile.
            try:
                driver.execute_script(profile.script)
            except Exception as exc:
                logger.debug(
                    "Fingerprint script eval on current document failed: %s", exc
                )

    def _apply_selenium_stealth(self, driver) -> None:
        """Apply selenium-stealth using the loaded fingerprint, not Windows defaults.

        selenium-stealth defaults to platform=None/webgl_vendor="Intel Inc."/
        renderer="Intel Iris OpenGL Engine", and both driver paths used to pass
        a hardcoded platform="Win32" on top of that. Because stealth() runs
        AFTER _apply_fingerprint_profile, those values won -- measured live in a
        crawler pod on 2026-07-29, on both `_create_undetected_driver` and
        `_create_stealth_driver`:

            userAgent      Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...
            platform       Win32          <- contradicts the UA outright
            webgl_vendor   no-webgl

        A macOS User-Agent reporting navigator.platform "Win32" is a
        self-contradiction no real browser produces, and PerimeterX (fox2now.com,
        fox4kc.com and the other Nexstar stations) exists to catch exactly that.

        Driving the arguments from the profile keeps one identity end to end.
        With no profile loaded the previous Win32 defaults are kept, so
        randomized-fingerprint behaviour is unchanged.
        """
        if not SELENIUM_STEALTH_AVAILABLE:
            return

        profile = self._fingerprint_profile
        languages = (
            profile.languages if profile and profile.languages else ["en-US", "en"]
        )
        kwargs: dict[str, Any] = {
            "languages": languages,
            "vendor": "Google Inc.",
            "fix_hairline": True,
        }
        if profile:
            if profile.user_agent:
                kwargs["user_agent"] = profile.user_agent
            if profile.navigator_platform:
                kwargs["platform"] = profile.navigator_platform
            if profile.webgl_vendor:
                kwargs["webgl_vendor"] = profile.webgl_vendor
            if profile.webgl_renderer:
                kwargs["renderer"] = profile.webgl_renderer
        else:
            # No profile: preserve the prior hardcoded identity rather than
            # letting stealth's own defaults drift the behaviour.
            kwargs.update(
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
            )

        try:
            stealth(driver, **kwargs)
            logger.debug(
                "Applied selenium-stealth (platform=%s, webgl_vendor=%s)",
                kwargs.get("platform"),
                kwargs.get("webgl_vendor"),
            )
        except Exception as exc:
            logger.debug("selenium-stealth application failed (non-fatal): %s", exc)

    def _set_user_agent_override(self, driver, user_agent: str) -> None:
        """Set User-Agent and client-hints with robust fallbacks across CDP versions.

        Some Chrome/ChromeDriver combinations reject the newer `userAgentMetadata`
        field on `Network.setUserAgentOverride` (invalid parameters). To be
        compatible, try the full payload first, then retry without
        `userAgentMetadata`, fall back to `Emulation.setUserAgentOverride`, and
        finally set explicit `sec-ch-*` headers via `Network.setExtraHTTPHeaders`.
        All failures are non-fatal and logged at debug level.
        """
        client_hints = None
        if self._fingerprint_profile and self._fingerprint_profile.client_hints:
            client_hints = deepcopy(self._fingerprint_profile.client_hints)

        def _try_network(payload: dict):
            try:
                driver.execute_cdp_cmd("Network.setUserAgentOverride", payload)
                return True, None
            except Exception as exc:
                logger.debug(
                    "Network.setUserAgentOverride failed for keys %s: %s",
                    list(payload.keys()),
                    exc,
                )
                return False, exc

        # 1) Try full payload (may include userAgentMetadata)
        full_payload = {"userAgent": user_agent}
        if client_hints:
            full_payload.update(client_hints)

        # If we've previously discovered the driver doesn't support the newer
        # userAgentMetadata parameter (cached on the driver), skip the full
        # payload attempt to avoid noisy failures. Also proactively check the
        # browser version once to opt-out of attempting a full payload for
        # Chrome builds known to reject the parameter (e.g., Chrome/143).
        if getattr(driver, "_supports_user_agent_metadata", True) is True:
            # Perform a one-time version check to avoid noisy 'Invalid parameters'
            # errors on known-broken browser builds (Chrome 143 observed rejecting the field).
            if not getattr(driver, "_user_agent_metadata_version_checked", False):
                try:
                    ver = driver.execute_cdp_cmd("Browser.getVersion", {})
                    prod = ver.get("product", "") if isinstance(ver, dict) else ""
                    try:
                        import re

                        m = re.search(r"Chrome/(\d+)\.", prod)
                        if m:
                            major = int(m.group(1))
                            # Chrome 143 was observed to reject any userAgentMetadata
                            if major >= 143:
                                try:
                                    driver._supports_user_agent_metadata = False
                                    logger.debug(
                                        "Browser.getVersion indicates Chrome %s; skipping userAgentMetadata attempt",
                                        major,
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    driver._user_agent_metadata_version_checked = True
                except Exception:
                    pass

            if getattr(driver, "_supports_user_agent_metadata", True) is True:
                ok, net_exc = _try_network(full_payload)
                if ok:
                    # Also set extra HTTP headers (sec-ch-ua*, Accept-Language) if available
                    try:
                        extra_headers: dict[str, str] = {}
                        if client_hints:
                            if client_hints.get("acceptLanguage"):
                                extra_headers["Accept-Language"] = client_hints[
                                    "acceptLanguage"
                                ]
                            ua_meta = (
                                client_hints.get("userAgentMetadata")
                                if client_hints
                                else None
                            )
                            if ua_meta:
                                brands = ua_meta.get("brands", []) or []
                                if brands:
                                    extra_headers["sec-ch-ua"] = ", ".join(
                                        f'"{b.get("brand")}";v="{b.get("version")}"'
                                        for b in brands
                                    )
                                extra_headers["sec-ch-ua-mobile"] = (
                                    "?1" if ua_meta.get("mobile") else "?0"
                                )
                                if client_hints.get("platform"):
                                    extra_headers["sec-ch-ua-platform"] = (
                                        f'"{client_hints["platform"]}"'
                                    )
                        if extra_headers:
                            driver.execute_cdp_cmd(
                                "Network.setExtraHTTPHeaders",
                                {"headers": extra_headers},
                            )
                    except Exception as e:
                        logger.debug(
                            "Network.setExtraHTTPHeaders after full payload failed: %s",
                            e,
                        )
                    return
                else:
                    # If the failure indicates 'Invalid parameters', mark the driver so
                    # we don't try the full payload again on subsequent calls.
                    try:
                        if net_exc and "invalid parameters" in str(net_exc).lower():
                            try:
                                driver._supports_user_agent_metadata = False
                                logger.debug(
                                    "Marked driver as not supporting userAgentMetadata"
                                )
                            except Exception:
                                pass
                            # Also log Browser.getVersion for easier debugging
                            try:
                                ver = driver.execute_cdp_cmd("Browser.getVersion", {})
                                logger.debug("Browser.getVersion reported: %s", ver)
                            except Exception:
                                pass
                    except Exception:
                        pass
        else:
            logger.debug(
                "Skipping full Network.setUserAgentOverride because driver flagged no support for userAgentMetadata"
            )

        # 2) Retry without userAgentMetadata (some CDP implementations reject it)
        reduced_payload = {"userAgent": user_agent}
        if client_hints:
            for k, v in client_hints.items():
                if k == "userAgentMetadata":
                    continue
                reduced_payload[k] = v

        ok, net_exc = _try_network(reduced_payload)
        if ok:
            try:
                extra_headers = {}
                ua_meta = (
                    client_hints.get("userAgentMetadata") if client_hints else None
                )
                if ua_meta:
                    brands = ua_meta.get("brands", []) or []
                    if brands:
                        extra_headers["sec-ch-ua"] = ", ".join(
                            f'"{b.get("brand")}";v="{b.get("version")}"' for b in brands
                        )
                    extra_headers["sec-ch-ua-mobile"] = (
                        "?1" if ua_meta.get("mobile") else "?0"
                    )
                if client_hints and client_hints.get("platform"):
                    extra_headers["sec-ch-ua-platform"] = (
                        f'"{client_hints["platform"]}"'
                    )
                if client_hints and client_hints.get("acceptLanguage"):
                    extra_headers["Accept-Language"] = client_hints["acceptLanguage"]
                if extra_headers:
                    driver.execute_cdp_cmd(
                        "Network.setExtraHTTPHeaders", {"headers": extra_headers}
                    )
            except Exception as e:
                logger.debug(
                    "Network.setExtraHTTPHeaders after reduced payload failed: %s", e
                )
            return

        # 3) Try Emulation.setUserAgentOverride as another alternative
        try:
            emu_payload: dict[str, str] = {"userAgent": user_agent}
            if client_hints and client_hints.get("platform"):
                emu_payload["platform"] = client_hints["platform"]
            driver.execute_cdp_cmd("Emulation.setUserAgentOverride", emu_payload)
            try:
                extra_headers = {}
                if client_hints and client_hints.get("acceptLanguage"):
                    extra_headers["Accept-Language"] = client_hints["acceptLanguage"]
                ua_meta = (
                    client_hints.get("userAgentMetadata") if client_hints else None
                )
                if ua_meta:
                    brands = ua_meta.get("brands", []) or []
                    if brands:
                        extra_headers["sec-ch-ua"] = ", ".join(
                            f'"{b.get("brand")}";v="{b.get("version")}"' for b in brands
                        )
                    extra_headers["sec-ch-ua-mobile"] = (
                        "?1" if ua_meta.get("mobile") else "?0"
                    )
                if client_hints and client_hints.get("platform"):
                    extra_headers["sec-ch-ua-platform"] = (
                        f'"{client_hints["platform"]}"'
                    )
                if extra_headers:
                    driver.execute_cdp_cmd(
                        "Network.setExtraHTTPHeaders", {"headers": extra_headers}
                    )
            except Exception as e:
                logger.debug(
                    "Network.setExtraHTTPHeaders after emulation fallback failed: %s",
                    e,
                )
            return
        except Exception as e:
            logger.debug("Emulation.setUserAgentOverride failed: %s", e)

        # 4) Final best-effort: set only the User-Agent
        try:
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride", {"userAgent": user_agent}
            )
        except Exception as e:
            logger.debug("Final CDP UA override failed (non-fatal): %s", e)

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
        options.add_argument("--disable-gpu")  # CRITICAL: Prevents GPU crash in K8s
        # Software GL, so a WebGL context exists at all. Without it there is no
        # GPU in the pod, getContext('webgl') returns null, and the fingerprint
        # profile's WebGL strings can never be applied -- a browser claiming
        # macOS with zero WebGL is itself an anti-bot signal. Measured 2026-07-29:
        # the deprecated --use-gl=swiftshader form does NOTHING on Chrome 143;
        # this is the flag that actually restores the context.
        options.add_argument("--enable-unsafe-swiftshader")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-plugins")
        if headless_mode:
            options.add_argument("--headless=new")
        # Additional stability flags for containerized environments
        options.add_argument("--disable-setuid-sandbox")
        # NOTE: --single-process removed - causes "Trace/breakpoint trap" crash in K8s
        # The flag was intended to prevent renderer subprocess issues but actually
        # crashes Chromium 143+ in containerized environments (discovered 2026-01-04)

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
        selenium_proxy = self._resolve_selenium_proxy()
        logger.info(
            f"🔀 Selenium proxy URL from env: {_mask_proxy_url(selenium_proxy)}"
        )

        # Chrome has no command-line syntax for proxy credentials. This used
        # to be solved with a Manifest V2 extension answering
        # chrome.webRequest.onAuthRequired -- but Chrome removed Manifest V2,
        # and by Chrome 150 that extension is ignored SILENTLY: no error, no
        # warning, just an unauthenticated browser. Every Selenium fetch then
        # got 407 from Squid and returned a ~0.2s "successful" navigation to
        # an empty error page. Production 2026-07-27: zero Selenium successes
        # since 07-25 across ~500 attempts; from inside a pod, no-cred -> 407
        # and with-cred -> 200. Manifest V3 cannot fix it either (blocking
        # onAuthRequired is gone).
        #
        # So credentials leave the browser entirely: a loopback relay speaks
        # unauthenticated proxy to Chrome and injects Proxy-Authorization
        # upstream. No browser release can break that the way MV2 removal did.
        try:
            relay_endpoint = get_relay_proxy(selenium_proxy)
            options.add_argument(f"--proxy-server={relay_endpoint}")
            logger.info(
                "🔀 Selenium proxying via auth relay %s -> %s",
                relay_endpoint,
                mask_proxy_url(selenium_proxy),
            )
        except Exception as exc:
            # Never fall through to a direct browser: an unproxied Selenium
            # egresses the pod IP, which is exactly the leak the proxy exists
            # to prevent.
            logger.error(
                "Proxy auth relay unavailable for %s (%s) - refusing to start "
                "an unproxied browser",
                mask_proxy_url(selenium_proxy),
                exc,
            )
            raise

        # Use ephemeral user-data-dir per attempt to avoid profile locks
        try:
            tmp_dir = Path(f"/tmp/uc-profile-{uuid.uuid4().hex}")
            tmp_dir.mkdir(parents=True, exist_ok=True)
            options.add_argument(f"--user-data-dir={tmp_dir}")
        except Exception as e_ud:
            logger.debug("Failed to create ephemeral user-data-dir: %s", e_ud)

        # Read optional binary paths from environment
        # Common envs: CHROME_BIN, GOOGLE_CHROME_BIN, CHROMEDRIVER_PATH
        chrome_bin = os.getenv("CHROME_BIN") or os.getenv("GOOGLE_CHROME_BIN") or None
        driver_path = os.getenv("CHROMEDRIVER_PATH") or None

        # Note: For undetected-chromedriver, we pass browser_executable_path as a parameter
        # to the uc.Chrome() constructor (below) instead of setting options.binary_location.
        # Setting both causes "Binary Location Must be a String" errors.

        # Create driver with version management
        try:
            # Try with subprocess first
            uc_kwargs = {
                "options": options,
                "version_main": None,
                "headless": headless_mode,
                "use_subprocess": True,
                "log_level": 3,
            }
            if driver_path:
                uc_kwargs["driver_executable_path"] = str(driver_path)
            if chrome_bin:
                uc_kwargs["browser_executable_path"] = str(chrome_bin)
            driver = uc.Chrome(**uc_kwargs)
        except Exception as e_primary:
            logger.warning(
                f"Failed to create undetected driver (use_subprocess=True): {e_primary}"
            )
            # Fallback: rebuild options fresh and try without subprocess; also try headless
            try:
                options_fb = uc.ChromeOptions()
                options_fb.page_load_strategy = "eager"
                for arg in [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    # See the note on the primary path: without software GL the
                    # profile's WebGL identity cannot be applied at all.
                    "--enable-unsafe-swiftshader",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                    "--remote-allow-origins=*",
                    "--disable-notifications",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-features=NetworkService,NetworkServiceInProcess",
                    "--disable-software-rasterizer",
                    "--disable-setuid-sandbox",
                ]:
                    options_fb.add_argument(arg)
                width, height = self._resolve_window_size()
                options_fb.add_argument(f"--window-size={width},{height}")
                realistic_ua_fb = self._resolve_selenium_user_agent()
                options_fb.add_argument(f"--user-agent={realistic_ua_fb}")
                # Proxy
                selenium_proxy = self._resolve_selenium_proxy()
                # Same relay as the primary path: Chrome cannot take proxy
                # credentials on the command line, and the old Manifest V2
                # auth extension is silently ignored by modern Chrome.
                try:
                    options_fb.add_argument(
                        f"--proxy-server={get_relay_proxy(selenium_proxy)}"
                    )
                except Exception as exc:
                    logger.error(
                        "Proxy auth relay unavailable (%s) - refusing an "
                        "unproxied fallback browser",
                        exc,
                    )
                    raise
                # Ephemeral profile
                try:
                    tmp_dir_fb = Path(f"/tmp/uc-profile-{uuid.uuid4().hex}")
                    tmp_dir_fb.mkdir(parents=True, exist_ok=True)
                    options_fb.add_argument(f"--user-data-dir={tmp_dir_fb}")
                except Exception:
                    pass
                uc_kwargs_fb = {
                    "options": options_fb,
                    "version_main": None,
                    "headless": True,  # Force headless on fallback
                    "use_subprocess": False,
                    "log_level": 3,
                }
                if driver_path:
                    uc_kwargs_fb["driver_executable_path"] = str(driver_path)
                if chrome_bin:
                    uc_kwargs_fb["browser_executable_path"] = str(chrome_bin)
                driver = uc.Chrome(**uc_kwargs_fb)
            except Exception as e_fallback:
                logger.warning(
                    f"Failed to create undetected driver (fallback use_subprocess=False, headless): {e_fallback}"
                )
                raise

        # Set timeouts - use longer timeouts for headful to allow JS challenges to resolve
        if headless_mode:
            # Short, aggressive timeouts for headless runs to keep CI fast
            driver.set_page_load_timeout(15)  # Reduced from 30
            driver.implicitly_wait(5)
            driver.command_executor._client_config.timeout = 30
        else:
            # Headful runs (real browser) need more time for heavy JS / challenge resolution
            driver.set_page_load_timeout(60)
            driver.implicitly_wait(5)
            driver.command_executor._client_config.timeout = 90

        # Enable collection of performance logs (CDP 'Network' events) for diagnostics
        try:
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        except Exception:
            pass

        # CRITICAL: Override User-Agent via CDP to hide headless indicator
        # The command-line arg doesn't always take effect, CDP is more reliable
        try:
            self._set_user_agent_override(driver, realistic_ua)
        except Exception as e:
            logger.debug(f"CDP UA override failed (non-fatal): {e}")

        # Apply additional selenium-stealth for maximum anti-detection
        # undetected-chromedriver handles basic stealth, but PerimeterX needs more.
        # Driven by the loaded fingerprint rather than hardcoded Windows values --
        # see _apply_selenium_stealth for the measurement that forced this.
        self._apply_selenium_stealth(driver)

        # Manual stealth enhancements for PerimeterX bypass
        try:
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            driver.execute_script("""
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
                """)
        except Exception as e:
            logger.debug(f"Manual stealth enhancements failed (non-fatal): {e}")

        # LAST, deliberately. Every stage above (stealth, the manual overrides)
        # redefines navigator properties, so whichever runs last wins. The
        # profile is the single source of truth for this browser's identity, so
        # it goes last and nothing overwrites it.
        self._apply_fingerprint_profile(driver)

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
        # See the note on _create_undetected_driver: software GL is what makes a
        # WebGL context exist, so the profile's WebGL identity can be applied.
        chrome_options.add_argument("--enable-unsafe-swiftshader")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument("--remote-allow-origins=*")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument(
            "--disable-features=NetworkService,NetworkServiceInProcess"
        )
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")

        width, height = self._resolve_window_size()
        chrome_options.add_argument(f"--window-size={width},{height}")

        # Realistic user agent
        realistic_ua = self._resolve_selenium_user_agent()
        chrome_options.add_argument(f"--user-agent={realistic_ua}")

        # CRITICAL: ALWAYS use Squid proxy for Selenium - no direct connections allowed
        selenium_proxy = self._resolve_selenium_proxy()
        # Via the auth relay -- credentials embedded in --proxy-server are
        # ignored by Chrome, which is how this path silently ran unauthenticated.
        chrome_options.add_argument(f"--proxy-server={get_relay_proxy(selenium_proxy)}")
        logger.debug(
            f"Squid proxy ENFORCED for stealth driver: {_mask_proxy_url(selenium_proxy)}"
        )

        # Exclude automation switches
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # Enable collection of performance logs (CDP 'Network' events) for diagnostics
        try:
            chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        except Exception:
            pass

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

        # Prefer configured profile; else use ephemeral per attempt to avoid locks
        if self._selenium_user_data_dir:
            self._maybe_configure_user_data_dir(chrome_options)
        else:
            try:
                tmp_dir = Path(f"/tmp/selenium-profile-{uuid.uuid4().hex}")
                tmp_dir.mkdir(parents=True, exist_ok=True)
                chrome_options.add_argument(f"--user-data-dir={tmp_dir}")
            except Exception as e_ud:
                logger.debug(
                    "Failed to create ephemeral user-data-dir (stealth): %s", e_ud
                )

        if driver_path:
            service = ChromeService(executable_path=str(driver_path))
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)

        # Apply selenium-stealth if available, driven by the loaded fingerprint
        # rather than hardcoded Windows values.
        self._apply_selenium_stealth(driver)

        # Manual stealth enhancements
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # NOTE: this block deliberately no longer forces navigator.platform to
        # 'Win32'. It was the third place a hardcoded Windows platform was
        # applied on top of a macOS fingerprint, and being the last writer it
        # won outright -- so a macOS User-Agent shipped with platform "Win32"
        # on this path too. platform now comes from the profile alone, applied
        # after this block.
        driver.execute_script("""
            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override permission API
            Object.defineProperty(navigator, 'permissions', {
                get: () => undefined
            });
        """)

        # Set timeouts - use longer timeouts for headful to allow JS challenges to resolve
        if headless_mode:
            driver.set_page_load_timeout(15)  # Reduced from 30
            driver.implicitly_wait(5)
            driver.command_executor._client_config.timeout = 30
        else:
            driver.set_page_load_timeout(60)
            driver.implicitly_wait(5)
            driver.command_executor._client_config.timeout = 90

        self._apply_fingerprint_profile(driver)

        # command executor timeout set above depending on headless/headful mode
        return driver

    @contextmanager
    def _phase(self, label: str):
        """Log how long a Selenium phase took, so a real pipeline run tells us
        where the per-article seconds actually go (page_source vs find_elements
        vs scroll vs the load itself). Greppable as 'SELENIUM_PHASE'. Cheap
        enough to leave on; remove once the driver timing is understood.
        """
        started = time.time()
        try:
            yield
        finally:
            logger.info("SELENIUM_PHASE %s %.2fs", label, time.time() - started)

    def _navigate_with_human_behavior(self, driver, url: str) -> bool:
        """Navigate to URL with minimal delays for faster content extraction."""
        try:
            # Navigate directly to target URL (no need for about:blank delay)
            domain = urlparse(url).netloc
            # Ensure single Selenium navigation per domain and perform FIRST-CONTACT via browser
            lock = self._get_domain_lock(domain)

            # Determine headless mode (used for retry wait heuristics)
            headless_mode = self._is_headless_selenium_mode()

            # Robust navigation: retry a few times with increasing timeouts so slow JS/verification
            # pages can complete and we avoid falling back to unblock proxy prematurely.
            max_attempts = 3
            timeouts = [15, 30, 60]
            success = False
            for attempt in range(1, max_attempts + 1):
                timeout = timeouts[min(attempt - 1, len(timeouts) - 1)]
                logger.info(
                    "FIRST-CONTACT: Selenium navigation attempt %d/%d to %s (timeout=%ds)",
                    attempt,
                    max_attempts,
                    url,
                    timeout,
                )
                try:
                    try:
                        driver.set_page_load_timeout(timeout)
                    except Exception:
                        pass  # Some driver implementations may not allow runtime change

                    # If an external cookie JSON is provided, attempt to import cookies for this domain
                    try:
                        imported = self._maybe_import_selenium_cookies(driver, domain)
                        if imported:
                            logger.info(
                                "Imported cookies for %s before navigation", domain
                            )
                    except Exception as e_c:
                        logger.debug("Cookie import step failed: %s", e_c)

                    with lock:
                        with self._phase("driver_get"):
                            driver.get(url)

                    # Wait for basic page load; allow more time on later attempts
                    wait_time = 5 if attempt == 1 else (10 if attempt == 2 else 15)
                    with self._phase("wait_for_body"):
                        WebDriverWait(driver, wait_time).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )

                    # Stop the load the instant <body> exists — page_load_strategy
                    # is 'eager' so the DOM is ready here while ads, trackers and
                    # auth/captcha iframes keep fetching through the proxy. Every
                    # DOM read after this (the captcha/subscription detectors, the
                    # human-scroll, then extraction) blocks until the load quiets
                    # down otherwise. This restores 47b5ad61's intent ("147s ->
                    # ~5-15s"): stop BEFORE anything reads the page. #388 stopped
                    # too late — the detectors run first and had already blocked.
                    #
                    # With the load halted here, every driver.page_source read
                    # downstream returns instantly AND reflects the live DOM, so
                    # a mutation (closing a modal, passing a challenge, scrolling
                    # in lazy content) is picked up by the next read with no stale
                    # cache to invalidate.
                    try:
                        with self._phase("window_stop"):
                            driver.execute_script("window.stop();")
                    except Exception:
                        pass

                    success = True
                    logger.info("Selenium navigation succeeded on attempt %d", attempt)
                    break

                except Exception as nav_exc:
                    logger.warning(
                        "Selenium navigation attempt %d failed for %s: %s",
                        attempt,
                        url,
                        nav_exc,
                    )

                    # Capture diagnostics: screenshot, browser logs, UA
                    try:
                        import base64
                        import json

                        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                        safe_domain = domain.replace(".", "_")
                        try:
                            b64 = driver.get_screenshot_as_base64()
                            sshot_path = (
                                f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}.png"
                            )
                            with open(sshot_path, "wb") as f:
                                f.write(base64.b64decode(b64))
                            logger.info("Wrote screenshot to %s", sshot_path)
                        except Exception as e_s:
                            logger.debug("Failed to capture screenshot: %s", e_s)

                        try:
                            logs = driver.get_log("browser")
                            log_path = f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}_browser.log"
                            with open(log_path, "w") as f:
                                json.dump(logs, f)
                            logger.info("Wrote browser logs to %s", log_path)
                        except Exception as e_l:
                            logger.debug("Failed to capture browser logs: %s", e_l)

                        try:
                            ua = driver.execute_script("return navigator.userAgent")
                            ua_path = f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}_ua.txt"
                            with open(ua_path, "w") as f:
                                f.write(str(ua))
                            logger.info("Wrote UA snapshot to %s", ua_path)

                            # Extended diagnostics: performance logs, cookies, localStorage, page HTML, navigator snapshot
                            try:
                                perf_logs = driver.get_log("performance")
                                perf_path = f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}_performance.log"
                                with open(perf_path, "w") as f:
                                    json.dump(perf_logs, f)
                                logger.info("Wrote performance logs to %s", perf_path)
                            except Exception as e_p:
                                logger.debug(
                                    "Failed to capture performance logs: %s", e_p
                                )

                            try:
                                cookies = driver.get_cookies()
                                cookies_path = f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}_cookies.json"
                                with open(cookies_path, "w") as f:
                                    json.dump(cookies, f)
                                logger.info("Wrote cookies to %s", cookies_path)
                            except Exception as e_c:
                                logger.debug("Failed to capture cookies: %s", e_c)

                            try:
                                local_storage = driver.execute_script(
                                    "var s = {}; for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); s[k] = localStorage.getItem(k); } return s;"
                                )
                                ls_path = f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}_localstorage.json"
                                with open(ls_path, "w") as f:
                                    json.dump(local_storage, f)
                                logger.info("Wrote localStorage to %s", ls_path)
                            except Exception as e_ls:
                                logger.debug("Failed to capture localStorage: %s", e_ls)

                            try:
                                page_html = driver.page_source
                                page_path = f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}_page.html"
                                with open(page_path, "w") as f:
                                    f.write(str(page_html))
                                logger.info("Wrote page HTML to %s", page_path)
                            except Exception as e_ph:
                                logger.debug("Failed to capture page HTML: %s", e_ph)

                            try:
                                nav = driver.execute_script(
                                    "return {ua:navigator.userAgent, webdriver:navigator.webdriver, platform:navigator.platform, vendor:navigator.vendor, languages:navigator.languages};"
                                )
                                nav_path = f"/tmp/selenium_{safe_domain}_{ts}_attempt{attempt}_navigator.json"
                                with open(nav_path, "w") as f:
                                    json.dump(nav, f)
                                logger.info("Wrote navigator snapshot to %s", nav_path)
                            except Exception as e_n:
                                logger.debug(
                                    "Failed to capture navigator snapshot: %s", e_n
                                )

                        except Exception as e_u:
                            logger.debug("Failed to capture UA: %s", e_u)

                    except Exception:
                        logger.debug(
                            "Diagnostics capture failed for attempt %d", attempt
                        )

                    # If this was the last attempt, log and let function return False below
                    if attempt == max_attempts:
                        logger.error(
                            "All Selenium navigation attempts failed for %s", url
                        )

            if not success:
                # If Selenium couldn't navigate successfully, do not fall back to HTTP session
                # for unblock domains - instead return False so the caller can decide to retry
                return False

            # If we reached here, navigation succeeded and we continue with standard checks
            # (e.g., subscription wall detection, challenge bypass, etc.)
            # Quick wait for page to stabilize
            time.sleep(0.5)  # Reduced from 1.0-2.0 seconds

            # Wrap detection and bypass logic in a resilient block - some driver operations
            # can raise low-level transport errors (HTTPConnectionPool read timeouts).
            try:
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
            except Exception as driver_exc:
                logger.warning(
                    "Driver operation raised exception during detection: %s; attempting one driver reset and retry",
                    driver_exc,
                )
                try:
                    self.close_persistent_driver()
                    driver = self.get_persistent_driver()
                    with lock:
                        try:
                            driver.get(url)
                        except Exception as nav_err:
                            logger.warning("Retry driver.get() failed: %s", nav_err)

                    retry_wait = 60 if not headless_mode else 10
                    try:
                        WebDriverWait(driver, retry_wait).until(
                            EC.presence_of_element_located((By.TAG_NAME, "body"))
                        )
                    except Exception as wex:
                        logger.warning("Retry wait after driver reset failed: %s", wex)

                    # Try detection and bypass again
                    try:
                        if self._detect_captcha_or_challenge(driver):
                            if self._try_bypass_challenge(driver, url):
                                logger.info("Bypassed after driver reset")
                                if not self._detect_subscription_wall(driver):
                                    return True
                    except Exception as e2:
                        logger.error(
                            "Retry detection after driver reset also failed: %s", e2
                        )
                        return False

                    return True
                except Exception as reset_exc:
                    logger.error("Driver reset attempt failed: %s", reset_exc)
                    return False

            # Try to close subscription modals/popups
            # Prevents false positives from subscription walls
            modal_closed = self._try_close_modals(driver, url)

            # Check for subscription wall (separate from CAPTCHA)
            if self._detect_subscription_wall(driver):
                logger.warning(
                    f"Subscription wall detected on {url} (modal_closed={modal_closed})"
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

                # Still paywalled: DON'T STOP extraction
                # We can still extract headline, byline, and partial content
                # even with subscription modal present
                logger.info(
                    f"Subscription modal present on {url} - "
                    "will extract headline and available text"
                )
                # Continue with extraction instead of returning False
                return True

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
                with self._phase("human_scroll"):
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
                    driver.execute_script(f"""
                        var event = new MouseEvent('mousemove', {{
                            clientX: {x},
                            clientY: {y}
                        }});
                        document.dispatchEvent(event);
                    """)
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
                # WPConsent CMP (used by Nexstar/kq2.com and other Nexstar stations)
                "#wpconsent-accept-all",
                ".wpconsent-accept-cookies.wpconsent-accept-all",
                "button[class*='wpconsent'][class*='accept' i]",
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
            with self._phase("subwall_page_source"):
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
                # Screenshot capture disabled - no longer saving paywall diagnostics
                # Screenshots were ephemeral in /tmp and not being persisted
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
                                if (
                                    "px-captcha" in selector
                                    or "human" in selector.lower()
                                ):
                                    logger.info(
                                        "Detected potential 'Press and Hold' challenge - using long click"
                                    )
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

    # A page carrying this much prose is showing an article, not a challenge.
    # Interstitials ("Just a moment...", "Attention Required") are near-empty by
    # design, so the threshold separates them without naming any of them.
    ARTICLE_CONTENT_MIN_CHARS = 1200
    ARTICLE_CONTENT_MIN_PARAGRAPHS = 5

    # A body this short is a teaser, not the story — a browser may still reveal the
    # real one, so Selenium stays on the table below this.
    #
    # 400 chars is ~66 words: shorter than a typical 1-3 paragraph paywall teaser,
    # and short enough that only 14.8% of genuinely complete articles fall under it.
    # Local news runs short — over 30 days the median `labeled` article was 2,190
    # chars (~365 words) and the 10th percentile 279 — so a higher cut wastes the
    # saving: 1200 chars would still escalate on 31% of complete stories.
    PAYWALL_STUB_MAX_CHARS = 400

    # Why the last capture was rejected ("empty" / "stub" /
    # "not_article_like"), or None when it was accepted.
    _last_capture_rejection: Optional[str] = None

    # Which paywall prompt the last capture matched, when the rejection
    # reason was "paywall". Recorded so the marker list can be audited
    # against real traffic rather than trusted.
    _last_paywall_marker: Optional[str] = None

    def _assess_capture_quality(self, content: str) -> Dict[str, Any]:
        """The measured signals behind a capture-quality verdict.

        Returned for every capture the gate judges -- accepted or rejected --
        so the heuristic can be EVALUATED rather than trusted: what share of
        captures each reason rejects, where the density/capitalisation
        distributions actually sit, and (paired with the Selenium body that
        follows a rejection) whether escalating was right. The thresholds
        that produced the verdict travel with it, so old rows stay readable
        after a retune.
        """
        stripped = (content or "").strip()
        quality: Dict[str, Any] = {
            "chars": len(stripped),
            "stub_threshold": self.PAYWALL_STUB_MAX_CHARS,
        }
        if not stripped:
            quality["article_like"] = False
            return quality

        try:
            body = strip_boilerplate(stripped)
            quality.update(
                {
                    "chars_after_strip": len(body),
                    "prose_density": round(prose_density(body), 4),
                    "capitalization_ratio": round(capitalization_ratio(body), 4),
                    "utility_word_rate": round(utility_word_rate(body), 4),
                    "article_like": looks_like_article(stripped),
                    "thresholds": {
                        "min_prose_density": MIN_PROSE_DENSITY,
                        "max_capitalization": MAX_CAPITALIZATION,
                        "max_utility_word_rate": MAX_UTILITY_WORD_RATE,
                    },
                }
            )
        except Exception as exc:  # never let measurement break extraction
            logger.debug("capture quality assessment failed: %s", exc)
            quality["error"] = str(exc)[:120]
        return quality

    def _selenium_would_add_value(self, result: dict, missing_fields: list) -> bool:
        """Whether launching a browser can plausibly recover the missing fields.

        Selenium earns its cost when it is the ONLY way to get the page: the site
        blocks bots, or the body needs interaction (closing a modal) or JS to
        render. It earns nothing as a metadata backfill — a second capture of the
        same HTML cannot beat the parsers that already ran on it.

        Measured over 30 days of production telemetry: of **6,366** extractions
        where a non-Selenium method already supplied the content, Selenium went on
        to supply the author exactly **once** and the publish_date **zero** times.
        Yet that path was ~92% of all Selenium invocations and consumed ~67% of
        worker capacity. Many of those articles simply have no byline to find.

        So gate on the BODY, not on metadata: escalate when the content is absent
        or short enough to be a teaser, and skip when we already hold a full story
        and are only missing author/date.
        """
        content = (result.get("content") or result.get("text") or "").strip()
        # Record the measured signals for EVERY decision, accept or reject.
        # Logging only rejections makes the heuristic unfalsifiable: you
        # cannot measure a false-positive rate, or retune MIN_PROSE_DENSITY /
        # MAX_CAPITALIZATION / MAX_UTILITY_WORD_RATE, from a sample that
        # excludes everything the gate let through.
        quality = self._assess_capture_quality(content)
        marker = looks_like_paywall(content)
        quality["paywall_marker"] = marker
        quality["is_paywall"] = bool(marker)
        result.setdefault("metadata", {})["capture_quality"] = quality
        if marker:
            # The save path files this as status="paywall" and keeps the
            # metadata the page did expose instead of storing the wall text.
            result["metadata"]["capture_rejected_as"] = "paywall"
            result["metadata"]["paywall_marker"] = marker

        if not content:
            self._last_capture_rejection = "empty"
            return True  # nothing captured at all — Selenium is the last resort
        if len(content) <= self.PAYWALL_STUB_MAX_CHARS:
            self._last_capture_rejection = "stub"
            return True  # teaser above a paywall; a real browser may reveal the body

        # Length alone says nothing about WHAT was captured. A consent wall, a
        # bot-challenge interstitial or a nav dump can all clear the stub
        # threshold and be accepted as an article. looks_like_article() already
        # answers this (prose density / capitalisation / utility-word rate, no
        # word-count floor) and comprehensive_telemetry already computes it to
        # set is_success -- but only ever to RECORD the failure, never to act on
        # it. Act on it: a body that is not writing is worth a browser.
        if not looks_like_article(content):
            # A wall is a special case of "not writing": the site served a
            # subscription prompt in place of the story. Selenium cannot beat
            # it -- the same wall is served to a real browser -- so escalating
            # costs a browser session (~3 min observed) and recovers nothing.
            # File it as paywalled instead and keep whatever the page did give
            # us (headline, byline, date live outside the wall).
            paywall_marker = looks_like_paywall(content)
            if paywall_marker:
                self._last_capture_rejection = "paywall"
                self._last_paywall_marker = paywall_marker
                logger.info(
                    "Capture for %s is a paywall prompt (%d chars, matched %r); "
                    "not escalating -- a browser gets the same wall",
                    result.get("url") or "?",
                    len(content),
                    paywall_marker,
                )
                return False

            self._last_capture_rejection = "not_article_like"
            logger.info(
                "Capture for %s is not article-like (%d chars); escalating",
                result.get("url") or "?",
                len(content),
            )
            return True

        # Full body in hand. Whatever metadata is still missing is missing from the
        # page itself, and re-fetching it will not conjure it.
        self._last_capture_rejection = None
        return False

    def _page_has_article_content(self, driver) -> bool:
        """Whether the captured page still carries a story.

        Used to tell a blocking wall from a widget that merely sits on the page:
        a wall replaces the article, a sign-in or subscription prompt does not.
        Deliberately structural — no vendor or publisher names — so it keeps
        working as publishers change providers.

        Parses the page's HTML *snapshot* — one ``page_source`` round-trip, then
        BeautifulSoup in-process — instead of reading each ``<p>.text`` live. The
        live read issued one WebDriver round-trip per element and each forced a
        layout reflow; instrumentation measured it at up to 124s on heavy pages
        versus ~0.2s for a snapshot parse, with ``driver_ping`` (a no-DOM
        round-trip) staying sub-2s the whole time — i.e. the cost was the
        per-element ``.text`` round-trips, not an unresponsive browser.

        Note the semantic shift: ``get_text()`` on the snapshot is ``textContent``
        (raw DOM text), not the rendered/visible text ``.text`` returned. For
        "is there article-length text here" that is fine, but be aware a paywall
        that CSS-hides an article still present in the DOM would now read as
        content-bearing; server-truncated paywalls (body absent from the DOM)
        still read as empty. Set ``SELENIUM_TEXT_DECOMPOSE=1`` to emit the extra
        probes that decompose round-trip chattiness from forced reflow.
        """
        try:
            with self._phase("pha_page_source"):
                html = driver.page_source or ""
            with self._phase("pha_bs_parse"):
                soup = BeautifulSoup(html, "html.parser")
                # script/style/noscript never carry article prose and would
                # inflate the textContent char count.
                for junk in soup(["script", "style", "noscript"]):
                    junk.decompose()
                paragraphs = soup.select("article p, main p, p")
                if len(paragraphs) < self.ARTICLE_CONTENT_MIN_PARAGRAPHS:
                    return False
                n = min(len(paragraphs), 40)
                chars = sum(len(p.get_text(strip=True)) for p in paragraphs[:n])
            logger.info("SELENIUM_PHASE pha_text_elements %d", n)

            if os.getenv("SELENIUM_TEXT_DECOMPOSE") == "1":
                self._decompose_text_cost(driver)

            return chars >= self.ARTICLE_CONTENT_MIN_CHARS
        except Exception:
            # Never let this probe decide by accident — if we cannot tell, fall
            # through to the existing detection rather than assuming safety.
            return False

    def _decompose_text_cost(self, driver) -> None:
        """Diagnostic (gated by SELENIUM_TEXT_DECOMPOSE=1): isolate *why* the old
        live ``.text`` loop was slow — round-trip chattiness vs forced reflow.

        Times, on the SAME page: a no-DOM round-trip (``driver_ping``), a single
        in-page ``textContent`` read (one round-trip, no reflow), and a single
        in-page ``innerText`` read (one round-trip, forces reflow). Read against
        the old per-element ``.text`` loop (~124s = 40 round-trips of rendered
        text):

        - textContent fast AND innerText fast → cost was the 40 round-trips.
        - textContent fast BUT innerText slow → forced reflow per rendered read
          dominates; a static snapshot (textContent) is what avoids it.
        - both slow → main-thread/layout contention even for a single in-page
          read — a deeper problem than the round-trip count.

        Never runs in production; best-effort, failures swallowed.
        """
        sel = "article p, main p, p"
        js = (
            "return Array.from(document.querySelectorAll(arguments[0]))"
            ".slice(0,40).map(e=>e[arguments[1]]||'').join('')"
        )
        try:
            with self._phase("driver_ping"):
                driver.execute_script("return 1")
        except Exception:
            pass
        try:
            with self._phase("pha_execjs_textcontent"):
                driver.execute_script(js, sel, "textContent")
        except Exception:
            pass
        try:
            with self._phase("pha_execjs_innertext"):
                driver.execute_script(js, sel, "innerText")
        except Exception:
            pass

    def _detect_captcha_or_challenge(self, driver) -> bool:
        """Detect if page contains CAPTCHA or other bot challenges.

        Returns True only for actual CAPTCHAs/bot challenges,
        NOT subscription modals or promotional CAPTCHAs.
        """
        try:
            with self._phase("captcha_page_source"):
                page_source = driver.page_source.lower()

            # 1. Check for subscription/paywall modals (these are NOT blockers)
            # If reCAPTCHA is inside a subscription modal, content is still accessible
            subscription_modal_keywords = [
                "subscribe",
                "membership",
                "paywall",
                "registration",
                "sign up",
                "create account",
                "limited free",
                "articles remaining",
                "monthly limit",
            ]

            has_subscription_keywords = (
                sum(
                    1
                    for keyword in subscription_modal_keywords
                    if keyword in page_source
                )
                >= 2
            )

            # 2. Check for actual CAPTCHA elements (high confidence)
            # BUT: if it's part of a subscription modal, treat it as non-blocking
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

            # A bot wall REPLACES the article; a sign-in or subscription widget
            # sits beside it. So the question isn't which vendor drew the
            # widget, it's whether the page still carries the story — which is
            # site-agnostic and doesn't rot as publishers change vendors.
            #
            # newstribune is the case that exposed the gap: it embeds reCAPTCHA
            # in a subscriber sign-in widget and carries only one subscription
            # keyword, so the >=2 keyword rule above missed it. Every article
            # then paid ~86s failing to "bypass" a login form before extracting
            # the article anyway — telemetry showed 11/11 selenium "success"
            # alongside "Could not bypass".
            with self._phase("page_has_article_content"):
                has_article_content = self._page_has_article_content(driver)

            # Only the soft, embeddable widgets get this exemption. Cloudflare
            # and PerimeterX challenges below are genuine walls and still block
            # even when markup happens to linger behind them.
            soft_captcha_selectors = (
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                "[class*='g-recaptcha']",
                "[class*='h-captcha']",
                "iframe[src*='captcha']",
            )

            for selector in captcha_selectors:
                try:
                    if driver.find_elements(By.CSS_SELECTOR, selector):
                        if has_article_content and selector in soft_captcha_selectors:
                            logger.info(
                                "Detected %s but the page still carries article "
                                "content (not blocking) — extracting normally",
                                selector,
                            )
                            return False
                        # If this is a subscription modal with a CAPTCHA, it's NOT blocking
                        if has_subscription_keywords and "recaptcha" in selector:
                            logger.info(
                                f"Detected reCAPTCHA in subscription promo (not blocking): {selector}"
                            )
                            # Still extract what we can - this is a promo modal, not a blocker
                            return False  # Not a blocking challenge

                        logger.info(f"Detected CAPTCHA element: {selector}")
                        # Screenshot capture disabled - no longer saving captcha diagnostics
                        # Screenshots were ephemeral in /tmp and not being persisted
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
            if any(
                k in page_source
                for k in ["recaptcha", "hcaptcha", "perimeterx", "px-captcha"]
            ):
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
        """Extract article author from HTML. Thin wrapper -- see
        _extract_author_with_source for the strategy that succeeded."""
        author, _source = self._extract_author_with_source(soup)
        return author

    def _extract_author_with_source(
        self, soup: BeautifulSoup
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract article author from HTML, and report WHICH strategy found it.

        Tries in order:
        1. Meta tags (most reliable)             -> source "meta_tag"
        2. CSS selectors for common byline classes -> source "css_selector"
        3. Text pattern search for "By {Name}"    -> source "body_text_pattern"

        The source is what makes byline provenance visible in telemetry
        (extraction_methods["author"] / final_field_attribution) instead of a
        flat "beautifulsoup" or "selenium" label that can't distinguish a
        structured meta tag from a raw "By Jane Smith" match in the body.
        """
        # Strategy 1: Try common meta tags first (most reliable)
        meta_selectors = [
            ("meta", {"name": "author"}),
            ("meta", {"property": "article:author"}),
            ("meta", {"name": "article:author"}),
            ("meta", {"name": "byl"}),
            ("meta", {"name": "sailthru.author"}),
        ]

        for selector, attrs in meta_selectors:
            element = soup.find(selector, _ensure_attrs_dict(attrs))
            if isinstance(element, Tag):
                author = element.get("content")
                if author is not None:
                    author_str = self._clean_author_text(str(author))
                    if author_str:
                        return author_str, "meta_tag"

        # Strategy 2: CSS selectors for common byline classes/elements
        css_selectors = [
            '[rel="author"]',
            '[itemprop="author"]',
            ".byline",
            ".byline__name",
            ".author",
            ".author-name",
            ".article-author",
            ".post-author",
            ".story-byline",
            ".article__byline",
            ".entry-author",
            # Creative Circle Media (warrensburgstarjournal, etc.)
            ".story-info",
            ".article-info",
            # eType Services (richmond-dailynews, etc.)
            ".field--name-uid",
            ".node__submitted",
        ]

        for selector in css_selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    author_txt = self._clean_author_text(element.get_text())
                    if author_txt and len(author_txt) < 200:
                        return author_txt, "css_selector"
            except Exception:
                continue

        # Strategy 3: Text pattern search for "By {Name}" in article header area
        # Focus on the first part of the page (header/info area)
        author = self._extract_author_by_text_pattern(soup)
        if author:
            return author, "body_text_pattern"

        return None, None

    def _clean_author_text(self, text: str) -> str:
        """Clean up author/byline text by removing common prefixes and normalizing."""
        if not text:
            return ""
        # Remove common prefixes
        cleaned = re.sub(
            r"^(By|Written by|Author:?|Reporter:?)\s+",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )
        # Remove extra whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Remove email addresses that follow the name
        cleaned = re.sub(r",?\s*[\w.+-]+@[\w.-]+\.\w+.*$", "", cleaned)
        # Remove "Posted" or date info that follows
        cleaned = re.sub(r"\s+Posted\s+.*$", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _extract_author_by_text_pattern(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract author from text patterns like 'By John Smith' in the HTML.

        Searches in likely locations: header, article info, first paragraphs.
        """
        # Pattern: "By {Name}" possibly followed by email or date
        by_pattern = re.compile(
            r"\bBy\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})"
            r"(?:\s*,?\s*[\w.+-]+@[\w.-]+\.\w+)?"
            r"(?:\s+Posted|\s+\||\s*$)",
            re.IGNORECASE,
        )

        # Search in likely areas: article info sections, first few elements
        search_areas = [
            soup.find(class_=re.compile(r"story.?info|article.?info", re.I)),
            soup.find(class_=re.compile(r"byline|author", re.I)),
            soup.find("article"),
        ]

        # Also check first N elements in body for "By" pattern
        body = soup.find("body")
        if body:
            # Get text content of early elements
            for elem in body.find_all(["p", "div", "span"], limit=30):
                text = elem.get_text()
                if text and "By " in text:
                    search_areas.append(elem)
                    break

        for area in search_areas:
            if not area:
                continue
            text = area.get_text(" ", strip=True)
            match = by_pattern.search(text)
            if match:
                author = match.group(1).strip()
                # Validate: should be 2-4 words, each capitalized
                words = author.split()
                if 1 <= len(words) <= 4:
                    # Check it looks like a name (not "By The Numbers" etc.)
                    if all(w[0].isupper() for w in words if w):
                        return author

        return None

    def _record_raw_html(self, html_text: str | bytes | None, method: str) -> None:
        """Remember the HTML a fetch method retrieved, for later archival.

        Methods run in succession until one satisfies the missing fields, so
        several may fetch the page before the chain ends. Recording per method
        lets ``_select_raw_html_for_archive`` keep the response belonging to
        whichever method actually supplied the content.
        """
        if not html_text:
            return

        if isinstance(html_text, bytes):
            try:
                html_str = html_text.decode("utf-8", errors="ignore")
            except Exception:
                return
        else:
            html_str = html_text

        self._raw_html_by_method[method] = html_str

    def _capture_reuse_enabled(self) -> bool:
        """Whether parsers may reuse a capture instead of fetching their own."""
        return os.getenv("EXTRACTION_REUSE_CAPTURE", "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    def _tls_capture_fallback_enabled(self) -> bool:
        """Whether the tls_client capture rung runs for unflagged domains too."""
        return os.getenv("TLS_CAPTURE_FALLBACK", "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    def _capture_for_parsing(self, current: str | None) -> str | None:
        """Return the page capture the next parser should work from.

        The chain is meant to fetch once and parse many times — every parser
        here accepts HTML and skips its own fetch when given it — but nothing
        used to hand a capture forward, so each fallback re-fetched the same
        URL. That costs requests, exposes us to bot protection repeatedly, and
        lets parsers disagree because they read different bytes.

        A Selenium capture wins over an HTTP one: it is the same page after
        JavaScript, which is strictly more of the article.

        Reuse is skipped while bot protection is flagged. The capture in hand
        may be a challenge page rather than the article, and letting the next
        method fetch for itself is exactly the escape hatch that recovers from
        that.
        """
        if not self._capture_reuse_enabled():
            return current

        if self._last_bot_protection_detection:
            return current

        selenium_capture = self._raw_html_by_method.get("selenium")
        if selenium_capture:
            return selenium_capture

        if current:
            return current

        if not self._raw_html_by_method:
            return None
        return self._raw_html_by_method[next(reversed(self._raw_html_by_method))]

    def _select_raw_html_for_archive(self, primary_method: str | None) -> None:
        """Pick which fetched response to archive for this extraction.

        Methods run in succession until the article is satisfied, so the copy
        worth keeping is the one fetched by the method that actually produced
        it — the same ``primary_method`` recorded as ``metadata.extraction_method``,
        so an archived page and the row describing it always agree.

        Some methods parse HTML a previous one fetched rather than fetching
        their own; when the winner has no response of its own we fall back to
        the last one fetched, which is the page it worked from.
        """
        if not self._raw_html_by_method:
            self._latest_raw_html = None
            self._latest_raw_html_method = None
            return

        winner = primary_method
        if winner not in self._raw_html_by_method:
            winner = next(reversed(self._raw_html_by_method))

        self._latest_raw_html = self._raw_html_by_method[winner]
        self._latest_raw_html_method = winner

    def get_last_raw_html(self) -> tuple[str | None, str | None]:
        """Return ``(html, method)`` for the most recent extraction."""
        return self._latest_raw_html, self._latest_raw_html_method

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
                                metadata["title_source"] = "json_ld"

                        # Get author (various formats)
                        if not metadata.get("author"):
                            author = item.get("author")
                            author_name = self._extract_author_from_jsonld(author)
                            if author_name:
                                metadata["author"] = author_name
                                # Per-field, alongside the shared cms_source
                                # below -- see the note on _apply_cms_metadata_fallback
                                # for why one shared label isn't enough.
                                metadata["author_source"] = "json_ld"

                        # Get datePublished
                        if not metadata.get("publish_date"):
                            pub_date = item.get("datePublished") or item.get(
                                "dateCreated"
                            )
                            if pub_date:
                                metadata["publish_date"] = pub_date
                                metadata["publish_date_source"] = "json_ld"

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
                metadata["title_source"] = "meta_tags"
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
                metadata["author_source"] = "meta_tags"
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
                            metadata["title_source"] = "datalayer"
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
                            metadata["author_source"] = "datalayer"
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
                            metadata["title_source"] = "nexstar"
                        if not metadata.get("author") and data.get("authorName"):
                            metadata["author"] = data["authorName"].strip()
                            metadata["author_source"] = "nexstar"
                        if not metadata.get("description") and data.get("description"):
                            metadata["description"] = data["description"].strip()
                        if not metadata.get("publish_date") and data.get(
                            "publicationDate"
                        ):
                            metadata["publish_date"] = data["publicationDate"]
                            metadata["publish_date_source"] = "nexstar"
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
                                    metadata["title_source"] = "window_data"
                            if not metadata.get("author"):
                                author = (
                                    content.get("author")
                                    or content.get("authorName")
                                    or content.get("byline")
                                )
                                if author and isinstance(author, str):
                                    metadata["author"] = author.strip()
                                    metadata["author_source"] = "window_data"
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
                        elif not _is_same_site_domain_alias(
                            article_domain, canonical_domain
                        ):
                            # Unknown domain but cross-domain canonical indicates syndication
                            # (e.g., Hearst TV stations syndicating between each other).
                            # The same-site check above rules out a domain alias for
                            # the SAME publisher first -- see _is_same_site_domain_alias.
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

        # Remove consent management platform (CMP) overlays before extraction.
        # These banners (WPConsent, OneTrust, TrustArc, etc.) inject large blocks
        # of cookie-policy text that extractors can mistake for article content.
        _cmp_id_patterns = re.compile(
            r"wpconsent|onetrust|trustarc|cookiebot|cookieconsent|"
            r"gdpr-consent|cookie-banner|cookie-notice|cmpbox|sp_message",
            re.I,
        )
        for element in soup.find_all(id=_cmp_id_patterns):
            element.decompose()
        for element in soup.find_all(
            class_=lambda c: bool(
                c and _cmp_id_patterns.search(" ".join(c) if isinstance(c, list) else c)
            )
        ):
            element.decompose()

        # Try common content selectors
        content_selectors = [
            "article",
            '[role="main"]',
            '[itemprop="articleBody"]',  # TownNews/BLOX CMS and schema.org microdata
            "story",  # Ellington CMS (californiademocrat, fultonsun, etc.)
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

        # Compute the body-text fallback up front so we can decide between it
        # and the meta-description lede below.
        body = soup.find("body")
        body_text = body.get_text(separator=" ", strip=True) if body else ""

        # Meta description fallback — for paywalled/blocked sites where the body
        # is only navigation + a subscription prompt. og:description /
        # meta[name=description] usually carry a 150-200 char publisher lede that
        # beats a junk body dump. Only prefer it when the body is too thin to be
        # the real article, so a normal page whose specific content selectors
        # merely missed still returns its full body text (not a truncated lede).
        if len(body_text) < 500:
            meta_attr_sets: List[Dict[str, Any]] = [
                {"property": "og:description"},
                {"name": "description"},
                {"name": "twitter:description"},
            ]
            for meta_attrs in meta_attr_sets:
                m = soup.find("meta", attrs=meta_attrs)
                if m:
                    content = (m.get("content") or "").strip()
                    if len(content) >= 60:
                        return content

        # Fallback to body
        if len(body_text) > 100:
            return body_text

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
