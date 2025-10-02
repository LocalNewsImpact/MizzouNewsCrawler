"""Discovery outcome tracking for detailed telemetry."""

from enum import Enum
from typing import Optional, Dict, Any


class DiscoveryOutcome(Enum):
    """Detailed outcomes for discovery attempts."""

    # Success cases
    NEW_ARTICLES_FOUND = "new_articles_found"           # Found new articles
    DUPLICATES_ONLY = "duplicates_only"                 # All duplicates
    EXPIRED_ONLY = "expired_only"                       # All too old
    MIXED_RESULTS = "mixed_results"                     # Mix of results

    # No content cases
    NO_ARTICLES_FOUND = "no_articles_found"             # No articles found
    RSS_MISSING = "rss_missing"                         # RSS unavailable
    CONTENT_BLOCKED = "content_blocked"                 # Blocked content

    # Technical failures
    HTTP_ERROR = "http_error"                           # HTTP 4xx/5xx errors
    TIMEOUT = "timeout"                                 # Request timeout
    CONNECTION_ERROR = "connection_error"               # Network/DNS issues
    PARSING_ERROR = "parsing_error"                     # Parsing failed
    CLOUDFLARE_BLOCKED = "cloudflare_blocked"           # Blocked by CF

    # System failures
    DATABASE_ERROR = "database_error"                   # Database failed
    UNKNOWN_ERROR = "unknown_error"                     # Unexpected error


class DiscoveryResult:
    """Detailed result from a discovery attempt."""

    def __init__(
        self,
        outcome: DiscoveryOutcome,
        articles_found: int = 0,
        articles_new: int = 0,
        articles_duplicate: int = 0,
        articles_expired: int = 0,
        error_details: Optional[str] = None,
        http_status: Optional[int] = None,
        method_used: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.outcome = outcome
        self.articles_found = articles_found
        self.articles_new = articles_new
        self.articles_duplicate = articles_duplicate
        self.articles_expired = articles_expired
        self.error_details = error_details
        self.http_status = http_status
        self.method_used = method_used
        self.metadata = metadata or {}

    @property
    def is_success(self) -> bool:
        """Whether this represents a successful discovery (found content)."""
        return self.outcome in {
            DiscoveryOutcome.NEW_ARTICLES_FOUND,
            DiscoveryOutcome.DUPLICATES_ONLY,
            DiscoveryOutcome.EXPIRED_ONLY,
            DiscoveryOutcome.MIXED_RESULTS
        }

    @property
    def is_content_success(self) -> bool:
        """Whether this found new content."""
        return self.outcome in {
            DiscoveryOutcome.NEW_ARTICLES_FOUND,
            DiscoveryOutcome.MIXED_RESULTS
        } and self.articles_new > 0

    @property
    def is_technical_failure(self) -> bool:
        """Whether this was a technical failure."""
        return self.outcome in {
            DiscoveryOutcome.HTTP_ERROR,
            DiscoveryOutcome.TIMEOUT,
            DiscoveryOutcome.CONNECTION_ERROR,
            DiscoveryOutcome.PARSING_ERROR,
            DiscoveryOutcome.CLOUDFLARE_BLOCKED,
            DiscoveryOutcome.DATABASE_ERROR,
            DiscoveryOutcome.UNKNOWN_ERROR
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/logging."""
        return {
            "outcome": self.outcome.value,
            "articles_found": self.articles_found,
            "articles_new": self.articles_new,
            "articles_duplicate": self.articles_duplicate,
            "articles_expired": self.articles_expired,
            "error_details": self.error_details,
            "http_status": self.http_status,
            "method_used": self.method_used,
            "is_success": self.is_success,
            "is_content_success": self.is_content_success,
            "is_technical_failure": self.is_technical_failure,
            **self.metadata
        }
