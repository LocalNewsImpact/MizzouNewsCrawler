"""News crawler module for discovering and fetching articles."""

import hashlib
import json
import logging
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from dateutil import parser as dateparser


class RateLimitError(Exception):
    """Exception raised when a domain is rate limited."""
    pass


# Enhanced extraction dependencies
try:
    from newspaper import Article as NewspaperArticle
    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False
    logging.warning("newspaper4k not available, falling back to BeautifulSoup only")

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
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
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


class NewsCrawler:
    """Main crawler class for discovering and fetching news articles."""

    def __init__(self, user_agent: str = None, timeout: int = 20, delay: float = 1.0):
        self.user_agent = user_agent or "Mozilla/5.0 (compatible; MizzouCrawler/1.0)"
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

                # Resolve relative URLs
                href = urljoin(seed_url, href)
                parsed_href = urlparse(href)

                # Normalize URL (remove fragment, query params for deduplication)
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
                f"Found {len(internal_urls)} internal, {len(external_urls)} external links"
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
        self, urls: Set[str], site_rules: Dict[str, any] = None
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

    def _is_likely_article(self, url: str, site_rules: Dict[str, any] = None) -> bool:
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
    
    def __init__(self, user_agent: str = None, timeout: int = 10):
        """Initialize ContentExtractor with anti-detection capabilities."""
        self.timeout = timeout  # Reduced from 20 for faster requests
        
        # Persistent driver for reuse across multiple extractions
        self._persistent_driver = None
        self._driver_creation_count = 0
        self._driver_reuse_count = 0
        
        # User agent pool for rotation
        self.user_agent_pool = [
            # Chrome on Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            # Chrome on macOS
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            # Firefox on Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            # Firefox on macOS
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
            # Safari on macOS
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        ]
        
        # Header variation pools
        self.accept_language_pool = [
            'en-US,en;q=0.9',
            'en-GB,en;q=0.9', 
            'en;q=0.9',
            'en-US,en;q=0.8,fr;q=0.6',
            'en-US,en;q=0.5'
        ]
        
        self.accept_encoding_pool = [
            'gzip, deflate, br',
            'gzip, deflate', 
            'gzip, deflate, br, zstd'
        ]
        
        # Track domain-specific sessions and user agents
        self.domain_sessions = {}
        self.domain_user_agents = {}
        self.request_counts = {}
        self.last_request_times = {}
        
        # Rate limiting and backoff management
        self.domain_request_times = {}  # Track request timestamps per domain
        self.domain_backoff_until = {}  # Track when domain is available again
        self.domain_error_counts = {}   # Track consecutive errors per domain
        self.base_delay = 1.0          # Base delay between requests (seconds)
        self.max_backoff = 300         # Maximum backoff time (5 minutes)
        
        # Set initial user agent
        self.current_user_agent = user_agent or random.choice(self.user_agent_pool)
        
        # Initialize primary session
        self._create_new_session()
        
        logger.info(f"ContentExtractor initialized with user agent rotation enabled")

    def _create_new_session(self):
        """Create a new session with current user agent and clear cookies."""
        # Initialize cloudscraper session for better Cloudflare handling
        if CLOUDSCRAPER_AVAILABLE and cloudscraper is not None:
            self.session = cloudscraper.create_scraper()
            logger.debug("Created new cloudscraper session")
        else:
            self.session = requests.Session()
            logger.debug("Created new requests session")
        
        # Set headers with some randomization
        self._set_session_headers()
        
    def _set_session_headers(self):
        """Set randomized headers for the current session."""
        headers = {
            "User-Agent": self.current_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": random.choice(self.accept_language_pool),
            "Accept-Encoding": random.choice(self.accept_encoding_pool),
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate", 
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
            "DNT": "1"
        }
        
        self.session.headers.update(headers)
        logger.debug(f"Updated session headers with UA: {self.current_user_agent[:50]}...")
        
    def _get_domain_session(self, url: str):
        """Get or create a domain-specific session with user agent rotation."""
        domain = urlparse(url).netloc
        
        # Check if domain is rate limited
        if self._check_rate_limit(domain):
            backoff_time = self.domain_backoff_until[domain] - time.time()
            logger.info(f"Domain {domain} is rate limited, backing off for "
                       f"{backoff_time:.0f} more seconds")
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
            
            # Rotate every 5 article calls with 20% jitter (4-6 requests)
            base_threshold = 5
            jitter = int(base_threshold * 0.2)  # 20% jitter = 1 request
            rotation_threshold = random.randint(
                base_threshold - jitter, base_threshold + jitter
            )
            if self.request_counts[domain] >= rotation_threshold:
                should_rotate = True
                self.request_counts[domain] = 0
                logger.info(
                    f"Rotating user agent for {domain} after "
                    f"{rotation_threshold} article calls (5±20% jitter)"
                )
        
        if should_rotate:
            # Select new user agent (avoid repeating the same one)
            available_agents = [ua for ua in self.user_agent_pool 
                             if ua != self.domain_user_agents.get(domain)]
            new_user_agent = random.choice(available_agents)
            
            # Create new session with clean cookies
            if CLOUDSCRAPER_AVAILABLE and cloudscraper is not None:
                new_session = cloudscraper.create_scraper()
            else:
                new_session = requests.Session()
            
            # Set randomized headers
            headers = {
                "User-Agent": new_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": random.choice(self.accept_language_pool),
                "Accept-Encoding": random.choice(self.accept_encoding_pool),
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none", 
                "Cache-Control": "max-age=0",
                "DNT": "1"
            }
            new_session.headers.update(headers)
            
            # Store new session and user agent for this domain
            self.domain_sessions[domain] = new_session
            self.domain_user_agents[domain] = new_user_agent
            
            logger.info(f"Created new session for {domain} with UA: "
                       f"{new_user_agent[:50]}...")
            logger.debug(f"Cleared cookies for domain {domain}")
        
        # Apply rate limiting delay before returning session
        self._apply_rate_limit(domain)
        
        return self.domain_sessions[domain]

    def get_rotation_stats(self) -> Dict[str, any]:
        """Get statistics about user agent rotation and session management."""
        return {
            "total_domains_accessed": len(self.domain_sessions),
            "active_sessions": len(self.domain_sessions),
            "domain_user_agents": {domain: ua[:50] + "..." if len(ua) > 50 else ua 
                                 for domain, ua in self.domain_user_agents.items()},
            "request_counts": self.request_counts.copy(),
            "user_agent_pool_size": len(self.user_agent_pool)
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
        """Apply rate limiting delay for a domain."""
        current_time = time.time()
        
        if delay is None:
            # Standard inter-request delay
            delay = random.uniform(1.0, 2.5)
        
        # Apply delay if needed
        if domain in self.domain_request_times:
            time_since_last = current_time - self.domain_request_times[domain]
            if time_since_last < delay:
                sleep_time = delay - time_since_last
                logger.debug(
                    f"Rate limiting: sleeping {sleep_time:.2f}s for {domain}"
                )
                time.sleep(sleep_time)
        
        # Update last request time
        self.domain_request_times[domain] = time.time()

    def _handle_rate_limit_error(
        self, domain: str, response: requests.Response = None
    ) -> None:
        """Handle rate limit errors with exponential backoff."""
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
        
        # Set backoff period
        self.domain_backoff_until[domain] = current_time + final_delay
        
        # Log the rate limit
        retry_after = response.headers.get('retry-after') if response else None
        if retry_after:
            try:
                retry_seconds = int(retry_after)
                logger.warning(
                    f"Rate limited by {domain}, server says retry "
                    f"after {retry_seconds}s, our backoff: "
                    f"{final_delay:.0f}s (attempt {error_count})"
                )
                # Use server's retry-after if it's longer than our backoff
                if retry_seconds > final_delay:
                    self.domain_backoff_until[domain] = (
                        current_time + retry_seconds
                    )
            except ValueError:
                pass
        else:
            logger.warning(
                f"Rate limited by {domain}, backing off for "
                f"{final_delay:.0f}s (attempt {error_count})"
            )

    def _reset_error_count(self, domain: str) -> None:
        """Reset error count for successful requests."""
        if domain in self.domain_error_counts:
            self.domain_error_counts[domain] = 0

    def _create_error_result(self, url: str, error_msg: str, 
                           metadata: Dict = None) -> Dict[str, any]:
        """Create a standardized error result."""
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
            "metadata": metadata or {}
        }
    
    def clear_all_sessions(self):
        """Clear all domain sessions and reset rotation state."""
        self.domain_sessions.clear()
        self.domain_user_agents.clear()
        self.request_counts.clear()
        self.last_request_times.clear()
        logger.info("Cleared all domain sessions and rotation state")

    def get_persistent_driver(self):
        """Get or create a persistent Selenium driver for reuse."""
        if self._persistent_driver is None:
            logger.info("Creating new persistent ChromeDriver for reuse")
            try:
                # Try undetected-chromedriver first (most advanced)
                if UNDETECTED_CHROME_AVAILABLE:
                    self._persistent_driver = self._create_undetected_driver()
                    self._driver_method = "undetected-chromedriver"
                elif SELENIUM_AVAILABLE:
                    self._persistent_driver = self._create_stealth_driver()
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
            logger.debug(f"Reusing persistent driver (reuse count: {self._driver_reuse_count})")
        
        return self._persistent_driver

    def close_persistent_driver(self):
        """Close the persistent driver and clean up resources."""
        if self._persistent_driver is not None:
            try:
                logger.info(f"Closing persistent driver after {self._driver_reuse_count + 1} uses "
                           f"(created {self._driver_creation_count} times)")
                self._persistent_driver.quit()
            except Exception as e:
                logger.warning(f"Error closing persistent driver: {e}")
            finally:
                self._persistent_driver = None
                self._driver_reuse_count = 0

    def get_driver_stats(self) -> Dict[str, any]:
        """Get statistics about driver usage."""
        return {
            "has_persistent_driver": self._persistent_driver is not None,
            "driver_creation_count": self._driver_creation_count,
            "driver_reuse_count": self._driver_reuse_count,
            "driver_method": getattr(self, '_driver_method', None)
        }

    def extract_article_data(self, html: str, url: str) -> Dict[str, any]:
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

    def extract_content(self, url: str, html: str = None,
                        metrics: Optional[object] = None) -> Dict[str, any]:
        """Fetch page if needed, extract article data using multiple methods.

        Uses intelligent field-level fallback:
        1. newspaper4k (primary) - extract all fields
        2. BeautifulSoup (fallback) - extract only missing fields
        3. Selenium (final fallback) - extract only remaining missing fields

        Args:
            url: URL to extract content from
            html: Optional pre-fetched HTML content
            metrics: Optional ExtractionMetrics object for telemetry tracking

        Returns a dictionary with keys: title, author, content, publish_date,
        metadata (original meta), and extracted_at.
        """
        logger.debug(f"Starting content extraction for {url}")

        # Initialize result structure
        result = {
            "url": url,
            "title": None,
            "author": None,
            "publish_date": None,
            "content": None,
            "metadata": {},
            "extracted_at": datetime.utcnow().isoformat(),
            "extraction_methods": {}  # Track which method worked for field
        }

        # Try newspaper4k first (primary method)
        if NEWSPAPER_AVAILABLE:
            try:
                logger.info(f"Attempting newspaper4k extraction for {url}")
                if metrics:
                    metrics.start_method("newspaper4k")

                newspaper_result = self._extract_with_newspaper(url, html)

                if newspaper_result:
                    # Copy all successfully extracted fields
                    self._merge_extraction_results(
                        result, newspaper_result, "newspaper4k", None, metrics
                    )
                    logger.info(f"newspaper4k extraction completed for {url}")
                    if metrics:
                        metrics.end_method("newspaper4k", True, None,
                                          newspaper_result)
                else:
                    if metrics:
                        metrics.end_method("newspaper4k", False,
                                          "No content extracted",
                                          newspaper_result or {})

            except Exception as e:
                logger.info(f"newspaper4k extraction failed for {url}: {e}")
                # Try to get any partial result with metadata (including HTTP status)
                partial_result = {}
                if hasattr(e, '__context__') and hasattr(e.__context__, 'response'):
                    # Some HTTP errors might have response info
                    pass
                
                # Check if this is an HTTP error with status code in the message
                error_str = str(e)
                if "Status code" in error_str:
                    import re
                    status_match = re.search(r'Status code (\d+)', error_str)
                    if status_match:
                        http_status = int(status_match.group(1))
                        partial_result = {
                            "metadata": {
                                "extraction_method": "newspaper4k",
                                "http_status": http_status
                            }
                        }
                
                if metrics:
                    metrics.end_method("newspaper4k", False, str(e), partial_result)

        # Check what fields are still missing
        missing_fields = self._get_missing_fields(result)

        # Try BeautifulSoup fallback for missing fields
        if missing_fields:
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
                        result, bs_result, "beautifulsoup", missing_fields,
                        metrics
                    )
                    logger.info(
                        f"BeautifulSoup extraction completed for {url}"
                    )
                    if metrics:
                        metrics.end_method("beautifulsoup", True, None,
                                          bs_result)
                else:
                    if metrics:
                        metrics.end_method("beautifulsoup", False,
                                          "No content extracted",
                                          bs_result or {})

            except Exception as e:
                logger.info(f"BeautifulSoup extraction failed for {url}: {e}")
                if metrics:
                    metrics.end_method("beautifulsoup", False, str(e), {})

        # Check what fields are still missing after BeautifulSoup
        missing_fields = self._get_missing_fields(result)

        # Try Selenium final fallback for remaining missing fields
        if missing_fields and SELENIUM_AVAILABLE:
            try:
                logger.info(
                    f"Attempting Selenium fallback for missing "
                    f"fields {missing_fields} on {url}"
                )
                if metrics:
                    metrics.start_method("selenium")

                selenium_result = self._extract_with_selenium(url)

                if selenium_result:
                    # Only copy still-missing fields
                    self._merge_extraction_results(
                        result, selenium_result, "selenium", missing_fields,
                        metrics
                    )
                    logger.info(f"Selenium extraction completed for {url}")
                    if metrics:
                        metrics.end_method("selenium", True, None,
                                          selenium_result)
                else:
                    if metrics:
                        metrics.end_method("selenium", False,
                                          "No content extracted",
                                          selenium_result or {})

            except Exception as e:
                logger.info(f"Selenium extraction failed for {url}: {e}")
                if metrics:
                    metrics.end_method("selenium", False, str(e), {})

        # Log final extraction summary
        final_missing = self._get_missing_fields(result)
        if final_missing:
            logger.warning(f"Could not extract fields {final_missing} "
                          f"for {url} with any method")
        else:
            logger.info(f"Successfully extracted all fields for {url}")

        # Complete extraction methods tracking for all fields
        self._complete_extraction_methods_tracking(result)
        
        # Determine the primary extraction method based on which extracted
        # the core content
        primary_method = self._determine_primary_extraction_method(result)
        
        # Clean up the metadata to remove internal tracking
        result_copy = result.copy()
        result_copy["metadata"]["extraction_methods"] = result[
            "extraction_methods"]
        result_copy["metadata"]["extraction_method"] = primary_method
        del result_copy["extraction_methods"]

        return result_copy

    def _get_missing_fields(self, result: Dict[str, any]) -> List[str]:
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

    def _merge_extraction_results(
        self,
        target: Dict[str, any],
        source: Dict[str, any],
        method: str,
        fields_to_copy: Optional[List[str]] = None,
        metrics: Optional[object] = None
    ) -> None:
        """Merge source extraction results into target, tracking methods.
        
        Args:
            target: The target result dictionary to update
            source: The source result dictionary to copy from
            method: The extraction method name for tracking
            fields_to_copy: If specified, only copy these fields.
                           If None, copy all.
            metrics: Optional ExtractionMetrics for tracking alternatives
        """
        if not source:
            return
            
        # Define all possible fields
        all_fields = ["title", "author", "content", "publish_date", "metadata"]
        
        # Determine which fields to process
        fields = fields_to_copy if fields_to_copy else all_fields
        
        for field in fields:
            source_value = source.get(field)
            
            # Only copy if source has a meaningful value and target doesn't
            if self._is_field_value_meaningful(field, source_value):
                current_value = target.get(field)
                if not self._is_field_value_meaningful(field, current_value):
                    target[field] = source_value
                    target["extraction_methods"][field] = method
                    logger.debug(
                        f"Copied {field} from {method} for extraction"
                    )
                elif (metrics and
                      hasattr(metrics, 'record_alternative_extraction')):
                    # Record when we found an alternative but didn't use it
                    metrics.record_alternative_extraction(
                        method, field, str(source_value), str(current_value)
                    )
                    logger.debug(
                        f"Alternative {field} found by {method} "
                        f"but not used (current from previous method)"
                    )

    def _is_field_value_meaningful(self, field: str, value: any) -> bool:
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
                    k for k in value.keys()
                    if k not in ["extraction_method", "extraction_methods"]
                ]
                return len(non_tracking_keys) > 0
            return bool(value)
        
        return bool(value)

    def _complete_extraction_methods_tracking(self, result: Dict[str, any]):
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

    def _determine_primary_extraction_method(
            self, result: Dict[str, any]) -> str:
        """Determine primary extraction method based on core content.
        
        Priority: content > title > author > publish_date > metadata
        """
        extraction_methods = result.get("extraction_methods", {})
        
        # Priority order - most important fields first
        priority_fields = [
            "content", "title", "author", "publish_date", "metadata"]
        
        for field in priority_fields:
            method = extraction_methods.get(field)
            if method and method != "none":
                logger.debug(
                    f"Primary extraction method: {method} (based on {field})")
                return method
        
        # Fallback to newspaper4k if no methods tracked
        logger.warning(
            "No extraction methods tracked, defaulting to newspaper4k")
        return "newspaper4k"

    def _is_extraction_successful(self, result: Dict[str, any]) -> bool:
        """Check if extraction result contains meaningful content."""
        if not result:
            return False
        
        # Must have at least title OR content
        title = result.get("title", "").strip()
        content = result.get("content", "").strip()
        
        return bool(title) or (bool(content) and len(content) > 100)

    def _extract_with_newspaper(self, url: str, html: str = None) -> Dict[str, any]:
        """Extract content using newspaper4k library with cloudscraper support."""
        article = NewspaperArticle(url)
        http_status = None
        
        if html:
            # Use provided HTML
            article.html = html
        else:
            # Use domain-specific session to fetch HTML
            try:
                session = self._get_domain_session(url)
                response = session.get(url, timeout=self.timeout)
                http_status = response.status_code
                domain = urlparse(url).netloc
                
                # Check for rate limiting
                if response.status_code == 429:
                    logger.warning(f"Rate limited (429) by {domain}")
                    self._handle_rate_limit_error(domain, response)
                    # Reset successful request count on rate limit
                    # and return error to skip this domain for now
                    return self._create_error_result(
                        url, "Rate limited", {"status": 429}
                    )
                elif response.status_code in [403, 503, 502, 504]:
                    # Possible rate limiting or bot detection
                    logger.warning(f"Possible bot detection ({response.status_code}) "
                                 f"by {domain}")
                    self._handle_rate_limit_error(domain, response)
                    return self._create_error_result(
                        url, f"Bot detection ({response.status_code})", 
                        {"status": response.status_code}
                    )
                
                # Check if request was successful
                if response.status_code == 200:
                    # Reset error count on successful request
                    self._reset_error_count(domain)
                    
                    # Use the downloaded HTML content to parse the article
                    article.html = response.text
                    ua = self.domain_user_agents.get(domain, "Unknown")
                    logger.debug(f"Successfully fetched content for {url} with "
                               f"UA: {ua[:30]}...")
                else:
                    logger.warning(f"Session returned status {response.status_code} "
                                 f"for {url}")
                    # Fallback to newspaper4k's built-in download
                    try:
                        article.download()
                    except Exception as download_e:
                        # Try to extract HTTP status from newspaper4k error message
                        error_str = str(download_e)
                        if "Status code" in error_str:
                            import re
                            status_match = re.search(r'Status code (\d+)', error_str)
                            if status_match:
                                http_status = int(status_match.group(1))
                                logger.warning(f"Newspaper4k download failed with "
                                             f"status {http_status}: {error_str}")
                        raise download_e
                    
            except RateLimitError as e:
                logger.warning(f"Domain rate limited, skipping: {e}")
                return self._create_error_result(url, str(e), {"rate_limited": True})
            except Exception as e:
                logger.warning(f"Session fetch failed for {url}: {e}, "
                             f"falling back to newspaper download")
                # Fallback to newspaper4k's built-in download
                try:
                    article.download()
                except Exception as download_e:
                    # Try to extract HTTP status from newspaper4k error message
                    error_str = str(download_e)
                    if "Status code" in error_str:
                        import re
                        status_match = re.search(r'Status code (\d+)', error_str)
                        if status_match:
                            http_status = int(status_match.group(1))
                            logger.warning(f"Newspaper4k download failed with status {http_status}: {error_str}")
                    raise download_e
        
        article.parse()
        
        # Extract publish date if available
        publish_date = None
        if hasattr(article, 'publish_date') and article.publish_date:
            publish_date = article.publish_date.isoformat()
        
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
                "cloudscraper_used": CLOUDSCRAPER_AVAILABLE and cloudscraper is not None,
                "http_status": http_status
            },
            "extracted_at": datetime.utcnow().isoformat(),
        }

    def _extract_with_beautifulsoup(self, url: str, html: str = None) -> Dict[str, any]:
        """Extract content using BeautifulSoup with bot-avoidance."""
        # Lazily fetch HTML if not provided
        page_html = html
        if page_html is None:
            try:
                # Get domain-specific session with rotated user agent
                session = self._get_domain_session(url)
                
                # Additional headers for better bot-avoidance
                headers = {
                    'Accept': ('text/html,application/xhtml+xml,'
                               'application/xml;q=0.9,image/webp,*/*;q=0.8'),
                    'Accept-Language': random.choice(self.accept_language_pool),
                    'Accept-Encoding': random.choice(self.accept_encoding_pool),
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Cache-Control': 'max-age=0',
                }
                
                # Temporarily update session headers (preserve existing)
                original_headers = session.headers.copy()
                session.headers.update(headers)
                
                try:
                    resp = session.get(url, timeout=self.timeout)
                    resp.raise_for_status()
                    page_html = resp.text
                    
                    domain = urlparse(url).netloc
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
                    
            except Exception as e:
                logger.warning(
                    f"Failed to fetch page for extraction {url}: {e}"
                )
                return {}

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
                )
            },
            "extracted_at": raw.get("extracted_at"),
        }
        
        return result

    def _extract_with_selenium(self, url: str) -> Dict[str, any]:
        """Extract content using persistent Selenium driver."""
        try:
            # Get the persistent driver (creates one if needed)
            driver = self.get_persistent_driver()
            stealth_method = getattr(self, '_driver_method', 'unknown')
            
            logger.debug(f"Using persistent {stealth_method} driver for {url}")
            
            # Navigate with human-like behavior
            success = self._navigate_with_human_behavior(driver, url)
            if not success:
                return {}
            
            # Extract content after ensuring page is loaded
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            
            return {
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
                    "driver_reused": self._driver_reuse_count > 0
                },
                "extracted_at": datetime.utcnow().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Selenium extraction failed for {url}: {e}")
            # If the driver fails, close it so a new one will be created next time
            if "driver" in str(e).lower() or "session" in str(e).lower():
                logger.warning("Driver error detected, closing persistent driver")
                self.close_persistent_driver()
            return {}

    def _create_undetected_driver(self):
        """Create undetected-chromedriver instance with maximum stealth."""
        import random
        
        # Configure undetected chrome options
        options = uc.ChromeOptions()
        
        # Basic stealth options
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        # Note: JavaScript and images enabled for modern news sites
        
        # Random viewport size (within realistic range)
        width = random.randint(1366, 1920)
        height = random.randint(768, 1080)
        options.add_argument(f"--window-size={width},{height}")
        
        # Realistic user agent (automatically handled by undetected-chrome)
        
        # Create driver with version management
        try:
            driver = uc.Chrome(
                options=options,
                version_main=None,  # Auto-detect
                headless=True,
                use_subprocess=True,
                log_level=3  # Suppress logs
            )
        except Exception as e:
            logger.warning(f"Failed to create undetected driver: {e}")
            raise
        
        # Set timeouts - reduced for faster extraction
        driver.set_page_load_timeout(15)  # Reduced from 30
        driver.implicitly_wait(5)  # Reduced from 10
        
        return driver

    def _create_stealth_driver(self):
        """Create regular Selenium driver with stealth enhancements."""
        import random
        
        # Configure Chrome options for maximum stealth
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument(
            "--disable-blink-features=AutomationControlled"
        )
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument(
            "--disable-background-timer-throttling"
        )
        chrome_options.add_argument(
            "--disable-backgrounding-occluded-windows"
        )
        chrome_options.add_argument("--disable-renderer-backgrounding")
        
        # Random realistic viewport
        width = random.randint(1366, 1920)
        height = random.randint(768, 1080)
        chrome_options.add_argument(f"--window-size={width},{height}")
        
        # Realistic user agent
        realistic_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        chrome_options.add_argument(f"--user-agent={realistic_ua}")
        
        # Exclude automation switches
        chrome_options.add_experimental_option(
            "excludeSwitches", ["enable-automation"]
        )
        chrome_options.add_experimental_option(
            'useAutomationExtension', False
        )
        
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
            "Object.defineProperty(navigator, 'webdriver', "
            "{get: () => undefined})"
        )
        
        driver.execute_script("""
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
        """)
        
        # Set timeouts - reduced for faster extraction
        driver.set_page_load_timeout(15)  # Reduced from 30
        driver.implicitly_wait(5)  # Reduced from 10
        
        return driver

    def _navigate_with_human_behavior(self, driver, url: str) -> bool:
        """Navigate to URL with minimal delays for faster content extraction."""
        import time
        import random
        
        try:
            # Navigate directly to target URL (no need for about:blank delay)
            driver.get(url)
            
            # Wait for basic page load with shorter timeout
            WebDriverWait(driver, 5).until(  # Reduced from 10
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Quick wait for page to stabilize
            time.sleep(0.5)  # Reduced from 1.0-2.0 seconds
            
            # Check for CAPTCHA or other challenges
            if self._detect_captcha_or_challenge(driver):
                logger.warning(f"CAPTCHA or challenge detected on {url}")
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
            page_height = driver.execute_script(
                "return document.body.scrollHeight"
            )
            viewport_height = driver.execute_script(
                "return window.innerHeight"
            )
            
            if page_height > viewport_height:
                # Simulate reading pattern: scroll down in chunks
                scroll_positions = []
                current_pos = 0
                
                while current_pos < page_height:
                    # Random scroll distance (realistic reading chunks)
                    scroll_distance = random.randint(200, 500)
                    current_pos = min(
                        current_pos + scroll_distance, page_height
                    )
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
            if hasattr(driver, 'execute_script'):
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

    def _detect_captcha_or_challenge(self, driver) -> bool:
        """Detect if page contains CAPTCHA or other bot challenges."""
        try:
            # Common CAPTCHA indicators
            captcha_indicators = [
                "captcha", "recaptcha", "hcaptcha",
                "challenge", "verify", "robot",
                "cloudflare", "access denied", "blocked"
            ]
            
            page_text = driver.page_source.lower()
            page_title = driver.title.lower()
            
            # Check page content for CAPTCHA keywords
            for indicator in captcha_indicators:
                if indicator in page_text or indicator in page_title:
                    return True
            
            # Check for common CAPTCHA elements
            captcha_selectors = [
                "[class*='captcha']",
                "[id*='captcha']",
                "[class*='recaptcha']",
                "[id*='recaptcha']",
                "iframe[src*='recaptcha']",
                ".cf-challenge-form",  # Cloudflare
                "#challenge-form"
            ]
            
            for selector in captcha_selectors:
                try:
                    if driver.find_elements(By.CSS_SELECTOR, selector):
                        return True
                except Exception:
                    continue
                    
            return False
            
        except Exception:
            return False

    def _is_title_suspicious(self, title: str) -> bool:
        """Detect potentially truncated or malformed titles."""
        if not title:
            return True
            
        title = title.strip()
        
        # Check for obvious truncation patterns
        suspicious_patterns = [
            # Starts with lowercase (likely truncated from middle of sentence)
            r'^[a-z]',
            # Starts with common word endings/fragments
            r'^(peat|ing|ed|ly|tion|ment|ness|ers?|s)\b',
            # Very short titles (less than 10 chars, too short for news)
            r'^.{1,9}$',
            # Contains only numbers/punctuation
            r'^[\d\s\-.,;:!?]+$'
        ]
        
        import re
        for i, pattern in enumerate(suspicious_patterns):
            # Apply IGNORECASE only to specific patterns, not the first one
            flags = re.IGNORECASE if i > 0 else 0
            if re.search(pattern, title, flags):
                logger.debug(f"Title flagged as suspicious: '{title}' "
                             f"(matched pattern: {pattern})")
                return True
                
        return False

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article title."""
        # Try Open Graph title first
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

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

        for selector, attrs in author_selectors:
            element = soup.find(selector, attrs)
            if element:
                if element.name == "meta":
                    author = element.get("content")
                else:
                    author = element.get_text().strip()

                if author:
                    return author

        return None

    def _extract_published_date(
        self, soup: BeautifulSoup, html: str
    ) -> Optional[str]:
        """Extract publication date using multiple heuristics."""
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
                        return parsed_date.isoformat() if parsed_date else None
                    except Exception:
                        continue

        # Try time element
        time_tag = soup.find("time")
        if time_tag and isinstance(time_tag, Tag):
            datetime_attr = time_tag.get("datetime")
            if datetime_attr:
                try:
                    parsed_date = dateparser.parse(str(datetime_attr))
                    return parsed_date.isoformat() if parsed_date else None
                except Exception:
                    pass

            # Try time text content
            time_text = time_tag.get_text().strip()
            if time_text:
                try:
                    parsed_date = dateparser.parse(time_text)
                    return parsed_date.isoformat() if parsed_date else None
                except Exception:
                    pass

        return None

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

    def _extract_meta_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract meta description."""
        try:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc:
                content = meta_desc.get("content")
                if content:
                    return str(content).strip()
        except (AttributeError, TypeError):
            pass

        try:
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                content = og_desc.get("content")
                if content:
                    return str(content).strip()
        except (AttributeError, TypeError):
            pass

        return None
