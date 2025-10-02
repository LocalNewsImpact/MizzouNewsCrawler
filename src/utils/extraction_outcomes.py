"""
Extraction outcome tracking for MizzouNewsCrawler content extraction.

This module provides detailed tracking and telemetry for content extraction
operations, designed to capture comprehensive metrics about extraction
success/failure types, content quality, and performance.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ExtractionOutcome(Enum):
    """Detailed outcomes for content extraction operations."""

    # Success cases
    CONTENT_EXTRACTED = "content_extracted"  # Full content extracted
    PARTIAL_CONTENT = "partial_content"  # Some content but incomplete

    # No content cases
    NO_CONTENT_FOUND = "no_content_found"  # Page loaded but no content
    EMPTY_RESPONSE = "empty_response"  # Server returned empty content
    PAYWALL_DETECTED = "paywall_detected"  # Content behind paywall

    # HTTP/Network errors
    HTTP_ERROR = "http_error"  # 4xx/5xx HTTP status codes
    TIMEOUT = "timeout"  # Request timeout
    CONNECTION_ERROR = "connection_error"  # Network connectivity issues
    SSL_ERROR = "ssl_error"  # SSL/TLS certificate issues
    DNS_ERROR = "dns_error"  # DNS resolution failure

    # Bot protection
    CLOUDFLARE_BLOCKED = "cloudflare_blocked"  # Cloudflare protection
    CAPTCHA_REQUIRED = "captcha_required"  # CAPTCHA challenge
    BOT_PROTECTION = "bot_protection"  # General bot protection
    RATE_LIMITED = "rate_limited"  # Rate limiting applied

    # Content issues
    PARSING_ERROR = "parsing_error"  # HTML parsing failed
    ENCODING_ERROR = "encoding_error"  # Text encoding issues
    JAVASCRIPT_REQUIRED = "javascript_required"  # Content requires JS

    # System errors
    DATABASE_ERROR = "database_error"  # Database operation failed
    UNKNOWN_ERROR = "unknown_error"  # Unexpected error


@dataclass
class ExtractionResult:
    """Structured result for content extraction operations."""

    # Core identifiers
    url: str
    article_id: int
    operation_id: str
    outcome: ExtractionOutcome

    # Timing metrics
    extraction_time_ms: int
    start_time: datetime
    end_time: datetime

    # HTTP metrics
    http_status_code: int | None = None
    response_size_bytes: int | None = None

    # Content validation flags
    has_title: bool = False
    has_content: bool = False
    has_author: bool = False
    has_publish_date: bool = False
    content_length: int | None = None

    # Quality metrics
    title_length: int | None = None
    author_count: int | None = None  # Number of authors detected

    # Field quality tracking
    title_quality_issues: list | None = None
    content_quality_issues: list | None = None
    author_quality_issues: list | None = None
    publish_date_quality_issues: list | None = None
    overall_quality_score: float = 1.0

    # Error details
    error_message: str | None = None
    error_type: str | None = None

    # Extracted content (for successful extractions)
    extracted_content: dict[str, Any] | None = None

    @property
    def is_success(self) -> bool:
        """Check if extraction was successful."""
        return self.outcome in {
            ExtractionOutcome.CONTENT_EXTRACTED,
            ExtractionOutcome.PARTIAL_CONTENT,
        }

    @property
    def is_content_success(self) -> bool:
        """Check if extraction found meaningful content."""
        return self.outcome == ExtractionOutcome.CONTENT_EXTRACTED

    @property
    def is_technical_failure(self) -> bool:
        """Check if failure was due to technical issues."""
        return self.outcome in {
            ExtractionOutcome.HTTP_ERROR,
            ExtractionOutcome.TIMEOUT,
            ExtractionOutcome.CONNECTION_ERROR,
            ExtractionOutcome.SSL_ERROR,
            ExtractionOutcome.DNS_ERROR,
            ExtractionOutcome.DATABASE_ERROR,
            ExtractionOutcome.PARSING_ERROR,
            ExtractionOutcome.ENCODING_ERROR,
            ExtractionOutcome.UNKNOWN_ERROR,
        }

    @property
    def is_bot_protection(self) -> bool:
        """Check if failure was due to bot protection."""
        return self.outcome in {
            ExtractionOutcome.CLOUDFLARE_BLOCKED,
            ExtractionOutcome.CAPTCHA_REQUIRED,
            ExtractionOutcome.BOT_PROTECTION,
            ExtractionOutcome.RATE_LIMITED,
        }

    @property
    def content_quality_score(self) -> float:
        """Calculate content quality score (0-1)."""
        if not self.is_success:
            return 0.0

        score = 0.0
        max_score = 4.0

        if self.has_title:
            score += 1.0
        if self.has_content:
            score += 1.0
        if self.has_author:
            score += 1.0
        if self.has_publish_date:
            score += 1.0

        return score / max_score
