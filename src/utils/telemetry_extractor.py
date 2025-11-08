"""
Enhanced content extractor with comprehensive telemetry integration.

This module provides a wrapper around the existing ContentExtractor that
adds detailed telemetry tracking, error categorization, and structured
result reporting for content extraction operations.
"""

import time
from datetime import datetime
from typing import Any

import requests
from requests.exceptions import ConnectionError, SSLError, Timeout

from crawler import ContentExtractor
from utils.extraction_outcomes import ExtractionOutcome, ExtractionResult


class TelemetryContentExtractor:
    """Enhanced ContentExtractor with comprehensive telemetry tracking."""

    def __init__(self, timeout: int = 20, user_agent: str | None = None):
        """Initialize the telemetry-enabled content extractor."""
        self.extractor = ContentExtractor()
        self.timeout = timeout
        # Use modern browser UA to avoid bot detection
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def extract_content_with_telemetry(
        self, url: str, article_id: int, operation_id: str, html: str | None = None
    ) -> ExtractionResult:
        """
        Extract content with comprehensive telemetry tracking.

        Returns ExtractionResult with detailed metrics and error
        categorization.
        """
        start_time = datetime.now()
        start_ms = time.time() * 1000

        # Initialize result with default values
        result_data = {
            "url": url,
            "article_id": article_id,
            "operation_id": operation_id,
            "outcome": ExtractionOutcome.UNKNOWN_ERROR,
            "extraction_time_ms": 0,
            "start_time": start_time,
            "end_time": start_time,
            "http_status_code": None,
            "response_size_bytes": None,
            "has_title": False,
            "has_content": False,
            "has_author": False,
            "has_publish_date": False,
            "content_length": None,
            "title_length": None,
            "author_count": None,
            "error_message": None,
            "error_type": None,
            "extracted_content": None,
        }

        try:
            # Fetch HTML if not provided
            if html is None:
                html, http_status, response_size = self._fetch_with_telemetry(url)
                result_data["http_status_code"] = http_status
                result_data["response_size_bytes"] = response_size

                if html is None:
                    # Fetch failed - outcome already set by
                    # _fetch_with_telemetry
                    end_time = datetime.now()
                    result_data["end_time"] = end_time
                    result_data["extraction_time_ms"] = (time.time() * 1000) - start_ms
                    return ExtractionResult(**result_data)

            # Extract content using enhanced extraction methods
            try:
                content_data = self.extractor.extract_content(url, html)

                if not content_data:
                    result_data["outcome"] = ExtractionOutcome.NO_CONTENT_FOUND
                    result_data["error_message"] = "No content extracted from HTML"
                else:
                    # Analyze extracted content quality
                    result_data.update(self._analyze_content_quality(content_data))
                    result_data["extracted_content"] = content_data

                    # Determine outcome based on content quality
                    if result_data["has_content"] and result_data["has_title"]:
                        result_data["outcome"] = ExtractionOutcome.CONTENT_EXTRACTED
                    elif result_data["has_title"] or result_data["has_content"]:
                        result_data["outcome"] = ExtractionOutcome.PARTIAL_CONTENT
                    else:
                        result_data["outcome"] = ExtractionOutcome.NO_CONTENT_FOUND

            except Exception as e:
                result_data["outcome"] = ExtractionOutcome.PARSING_ERROR
                result_data["error_message"] = str(e)
                result_data["error_type"] = type(e).__name__

        except Exception as e:
            # Map error messages to appropriate outcomes
            result_data["outcome"] = self._determine_outcome_from_error(str(e))
            result_data["error_message"] = str(e)
            result_data["error_type"] = type(e).__name__

        # Finalize timing
        end_time = datetime.now()
        result_data["end_time"] = end_time
        result_data["extraction_time_ms"] = int((time.time() * 1000) - start_ms)

        return ExtractionResult(**result_data)

    def _determine_outcome_from_error(self, error_message: str) -> ExtractionOutcome:
        """Map error message to appropriate extraction outcome."""
        error_msg = error_message.upper()

        if "CLOUDFLARE" in error_msg:
            return ExtractionOutcome.CLOUDFLARE_BLOCKED
        elif "CAPTCHA" in error_msg:
            return ExtractionOutcome.CAPTCHA_REQUIRED
        elif "BOT_PROTECTION" in error_msg or "BOT_DETECTED" in error_msg:
            return ExtractionOutcome.BOT_PROTECTION
        elif "RATE_LIMITED" in error_msg or "TOO_MANY_REQUESTS" in error_msg:
            return ExtractionOutcome.RATE_LIMITED
        elif "PAYWALL" in error_msg:
            return ExtractionOutcome.PAYWALL_DETECTED
        elif "TIMEOUT" in error_msg:
            return ExtractionOutcome.TIMEOUT
        elif "DNS_ERROR" in error_msg:
            return ExtractionOutcome.DNS_ERROR
        elif "SSL_ERROR" in error_msg:
            return ExtractionOutcome.SSL_ERROR
        elif "CONNECTION_ERROR" in error_msg:
            return ExtractionOutcome.CONNECTION_ERROR
        elif "HTTP_ERROR" in error_msg:
            if "404" in error_msg:
                return ExtractionOutcome.PAGE_NOT_FOUND
            elif any(code in error_msg for code in ["400", "401", "403", "405"]):
                return ExtractionOutcome.HTTP_ERROR
            elif any(code in error_msg for code in ["500", "502", "503", "504"]):
                return ExtractionOutcome.SERVER_ERROR
            else:
                return ExtractionOutcome.HTTP_ERROR
        elif "EMPTY_RESPONSE" in error_msg:
            return ExtractionOutcome.NO_CONTENT_FOUND
        else:
            return ExtractionOutcome.UNKNOWN_ERROR

    def _fetch_with_telemetry(
        self, url: str
    ) -> tuple[str | None, int | None, int | None]:
        """
        Fetch HTML with detailed error categorization.

        Returns (html, http_status_code, response_size_bytes)
        """
        try:
            response = self.session.get(url, timeout=self.timeout)

            # Check for bot protection indicators
            if self._is_bot_protection(response):
                if "cloudflare" in response.text.lower():
                    raise Exception("CLOUDFLARE_BLOCKED")
                elif "captcha" in response.text.lower():
                    raise Exception("CAPTCHA_REQUIRED")
                else:
                    raise Exception("BOT_PROTECTION")

            # Check HTTP status
            if response.status_code == 429:
                raise Exception("RATE_LIMITED")
            elif 400 <= response.status_code < 500:
                if response.status_code == 404:
                    raise Exception(
                        f"HTTP_ERROR: Page not found ({response.status_code})"
                    )
                else:
                    raise Exception(
                        f"HTTP_ERROR: Client error ({response.status_code})"
                    )
            elif response.status_code >= 500:
                raise Exception(f"HTTP_ERROR: Server error ({response.status_code})")

            response.raise_for_status()

            # Check for empty response
            if not response.text.strip():
                raise Exception("EMPTY_RESPONSE")

            # Check for paywall indicators
            if self._is_paywall(response.text):
                raise Exception("PAYWALL_DETECTED")

            return response.text, response.status_code, len(response.content)

        except Timeout:
            raise Exception("TIMEOUT")
        except ConnectionError:
            raise Exception("CONNECTION_ERROR")
        except SSLError:
            raise Exception("SSL_ERROR")
        except requests.exceptions.RequestException as e:
            if "DNS" in str(e).upper():
                raise Exception("DNS_ERROR")
            else:
                raise Exception(f"HTTP_ERROR: {str(e)}")
        except Exception as e:
            # Re-raise our custom exceptions
            if str(e).startswith(
                (
                    "CLOUDFLARE_",
                    "CAPTCHA_",
                    "BOT_",
                    "RATE_",
                    "HTTP_",
                    "EMPTY_",
                    "PAYWALL_",
                )
            ):
                raise
            else:
                raise Exception(f"CONNECTION_ERROR: {str(e)}")

    def _is_bot_protection(self, response) -> bool:
        """Check if response indicates bot protection."""
        # More specific indicators of actual blocking, not just
        # presence of services
        blocking_indicators = [
            "checking your browser",
            "cloudflare ray id",
            "ddos protection by cloudflare",
            "access denied",
            "blocked by",
            "captcha",
            "bot protection",
            "security check",
            "please enable javascript",
            "please wait while we verify",
            "under attack mode",
            "browser check",
        ]

        text = response.text.lower()
        # Only trigger if we see actual blocking indicators
        return any(indicator in text for indicator in blocking_indicators)

    def _is_paywall(self, html: str) -> bool:
        """Check if content appears to be behind a paywall."""
        paywall_indicators = [
            "subscribe to continue",
            "paywall",
            "premium content",
            "sign up to read",
            "subscribe for full access",
            "login to continue",
            "this article is for subscribers",
        ]

        text = html.lower()
        return any(indicator in text for indicator in paywall_indicators)

    def _analyze_content_quality(self, content_data: dict[str, Any]) -> dict[str, Any]:
        """Analyze the quality and completeness of extracted
        content."""
        analysis: dict[str, Any] = {
            "has_title": bool(content_data.get("title", "").strip()),
            "has_content": bool(content_data.get("content", "").strip()),
            "has_author": bool(content_data.get("author", "").strip()),
            "has_publish_date": bool(
                content_data.get("published_date") or content_data.get("publish_date")
            ),
            "content_length": None,
            "title_length": None,
            "author_count": None,
        }

        # Calculate lengths
        if analysis["has_title"]:
            analysis["title_length"] = len(content_data["title"].strip())

        if analysis["has_content"]:
            analysis["content_length"] = len(content_data["content"].strip())

        if analysis["has_author"]:
            # Count number of authors (simple comma-based split)
            authors = content_data["author"].strip()
            analysis["author_count"] = len(
                [a.strip() for a in authors.split(",") if a.strip()]
            )

        # Add detailed field quality analysis
        field_quality = self._analyze_field_quality(content_data)
        analysis.update(field_quality)

        return analysis

    def _analyze_field_quality(self, content_data: dict[str, Any]) -> dict[str, Any]:
        """Perform detailed quality analysis for each extracted field."""
        quality_analysis: dict[str, Any] = {
            "title_quality_issues": [],
            "content_quality_issues": [],
            "author_quality_issues": [],
            "publish_date_quality_issues": [],
            "overall_quality_score": 1.0,
        }

        # Analyze title quality
        title = content_data.get("title", "").strip()
        if title:
            if len(title) < 10:
                quality_analysis["title_quality_issues"].append("too_short")
            if len(title) > 200:
                quality_analysis["title_quality_issues"].append("too_long")
            if self._contains_html_tags(title):
                quality_analysis["title_quality_issues"].append("contains_html")
            if self._contains_js_artifacts(title):
                quality_analysis["title_quality_issues"].append("contains_js")
            if title.lower() in ["untitled", "no title", "title", ""]:
                quality_analysis["title_quality_issues"].append("placeholder_text")
        else:
            quality_analysis["title_quality_issues"].append("missing")

        # Analyze content quality
        content = content_data.get("content", "").strip()
        if content:
            if len(content) < 100:
                quality_analysis["content_quality_issues"].append("too_short")
            if self._contains_html_tags(content):
                quality_analysis["content_quality_issues"].append("contains_html")
            if self._contains_js_artifacts(content):
                quality_analysis["content_quality_issues"].append("contains_js")
            if self._is_mostly_navigation(content):
                quality_analysis["content_quality_issues"].append("navigation_text")
            if self._contains_error_messages(content):
                quality_analysis["content_quality_issues"].append("error_messages")
        else:
            quality_analysis["content_quality_issues"].append("missing")

        # Analyze author quality
        author = content_data.get("author", "").strip()
        if author:
            if len(author) < 2:
                quality_analysis["author_quality_issues"].append("too_short")
            if len(author) > 100:
                quality_analysis["author_quality_issues"].append("too_long")
            if self._contains_html_tags(author):
                quality_analysis["author_quality_issues"].append("contains_html")
            if author.lower() in ["author", "staff", "unknown", "anonymous"]:
                quality_analysis["author_quality_issues"].append("placeholder_text")
        else:
            quality_analysis["author_quality_issues"].append("missing")

        # Analyze publish date quality
        publish_date = content_data.get("publish_date") or content_data.get(
            "published_date"
        )
        if publish_date:
            if not self._is_valid_date_format(publish_date):
                quality_analysis["publish_date_quality_issues"].append("invalid_format")
            if self._is_future_date(publish_date):
                quality_analysis["publish_date_quality_issues"].append("future_date")
            if self._is_too_old_date(publish_date):
                quality_analysis["publish_date_quality_issues"].append(
                    "suspiciously_old"
                )
        else:
            quality_analysis["publish_date_quality_issues"].append("missing")

        # Calculate overall quality score
        total_issues = (
            len(quality_analysis["title_quality_issues"])
            + len(quality_analysis["content_quality_issues"])
            + len(quality_analysis["author_quality_issues"])
            + len(quality_analysis["publish_date_quality_issues"])
        )

        # Score: 1.0 (perfect) down to 0.0 (many issues)
        quality_analysis["overall_quality_score"] = max(0.0, 1.0 - (total_issues * 0.1))

        return quality_analysis

    def _contains_html_tags(self, text: str) -> bool:
        """Check if text contains HTML tags."""
        import re

        return bool(re.search(r"<[^>]+>", text))

    def _contains_js_artifacts(self, text: str) -> bool:
        """Check if text contains JavaScript artifacts."""
        # More specific JS patterns to avoid false positives with natural
        # language
        import re

        # Look for specific JS function/method patterns
        js_patterns = [
            r"function\s*\(",  # function declarations
            r"document\.[a-zA-Z]",  # document.method calls
            r"window\.[a-zA-Z]",  # window.property access
            r"var\s+[a-zA-Z]",  # variable declarations
            r"const\s+[a-zA-Z]",  # const declarations
            r"let\s+[a-zA-Z]",  # let declarations
            r"addEventListener\s*\(",  # event listeners
            r"getElementById\s*\(",  # DOM methods
            r"\$\s*\(",  # jQuery
            r"console\.[a-zA-Z]",  # console methods
            r"=>\s*{",  # arrow functions
            r"\.then\s*\(",  # promise chains
            r"\.catch\s*\(",  # error handling
            r"JSON\.[a-zA-Z]",  # JSON methods
        ]

        # Also check for combinations of JS-specific terms
        js_keywords = ["undefined", "typeof", "instanceof", "prototype"]
        text_lower = text.lower()

        # Count JS pattern matches
        pattern_matches = sum(
            1 for pattern in js_patterns if re.search(pattern, text, re.IGNORECASE)
        )

        # Count JS keyword matches
        keyword_matches = sum(1 for keyword in js_keywords if keyword in text_lower)

        # Require multiple indicators or very specific patterns
        return (
            pattern_matches >= 2
            or keyword_matches >= 2
            or any(
                re.search(pattern, text, re.IGNORECASE) for pattern in js_patterns[:3]
            )
        )  # Strong indicators

    def _is_mostly_navigation(self, text: str) -> bool:
        """Check if content is mostly navigation/menu text."""
        nav_indicators = [
            "home",
            "about",
            "contact",
            "menu",
            "navigation",
            "breadcrumb",
            "skip to content",
            "main menu",
            "search",
            "login",
            "register",
        ]
        text_lower = text.lower()
        nav_count = sum(1 for indicator in nav_indicators if indicator in text_lower)
        words = len(text.split())
        return nav_count > 3 and words < 50

    def _contains_error_messages(self, text: str) -> bool:
        """Check if content contains error messages."""
        error_indicators = [
            "404",
            "not found",
            "page not found",
            "error",
            "something went wrong",
            "access denied",
            "forbidden",
            "server error",
            "maintenance",
        ]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in error_indicators)

    def _is_valid_date_format(self, date_str: str) -> bool:
        """Check if date string is in a valid format."""
        from datetime import datetime

        # Common date formats
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",  # ISO format with timezone
            "%Y-%m-%dT%H:%M:%S",  # ISO format without timezone
            "%Y-%m-%d",  # YYYY-MM-DD
            "%m/%d/%Y",  # MM/DD/YYYY
            "%d/%m/%Y",  # DD/MM/YYYY
            "%B %d, %Y",  # Month DD, YYYY
        ]

        for fmt in formats:
            try:
                datetime.strptime(date_str.replace("+00:00", ""), fmt.replace("%z", ""))
                return True
            except ValueError:
                continue
        return False

    def _is_future_date(self, date_str: str) -> bool:
        """Check if date is in the future (suspicious)."""
        from datetime import datetime, timezone

        try:
            # Parse the date and compare with current time
            if "T" in date_str:
                # ISO format
                date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                # Simple date
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                date_obj = date_obj.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            return date_obj > now
        except (ValueError, TypeError):
            return False

    def _is_too_old_date(self, date_str: str) -> bool:
        """Check if date is suspiciously old (> 10 years)."""
        from datetime import datetime, timedelta, timezone

        try:
            if "T" in date_str:
                date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                date_obj = date_obj.replace(tzinfo=timezone.utc)

            ten_years_ago = datetime.now(timezone.utc) - timedelta(days=3650)
            return date_obj < ten_years_ago
        except (ValueError, TypeError):
            return False
