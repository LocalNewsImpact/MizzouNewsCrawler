"""URL normalization utilities for consistent deduplication."""

from urllib.parse import urlparse, urlunparse
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """
    Normalize a URL for consistent deduplication by removing fragments
    and query parameters.

    Args:
        url: The URL to normalize

    Returns:
        Normalized URL with fragments and query parameters removed

    Examples:
        normalize_url("https://example.com/story#section")
            -> "https://example.com/story"
        normalize_url("https://example.com/story?ref=home")
            -> "https://example.com/story"
        normalize_url("https://example.com/story?id=123#top")
            -> "https://example.com/story"
    """
    if not url or not url.strip():
        return url

    try:
        parsed = urlparse(url.strip())

        # Reconstruct URL without fragment and query parameters
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,  # Keep params (might be part of path structure)
            '',  # Remove query
            ''   # Remove fragment
        ))

        # Clean up any trailing slashes for consistency (except for root)
        if normalized.endswith('/') and len(normalized) > 1:
            # Only remove trailing slash if there's a path component
            if parsed.path and parsed.path != '/':
                normalized = normalized.rstrip('/')

        return normalized

    except Exception as e:
        logger.warning(f"Failed to normalize URL '{url}': {e}")
        return url  # Return original if parsing fails


def is_same_article_url(url1: str, url2: str) -> bool:
    """
    Check if two URLs represent the same article after normalization.

    Args:
        url1: First URL to compare
        url2: Second URL to compare

    Returns:
        True if the URLs represent the same article

    Examples:
        is_same_article_url("https://example.com/story",
                           "https://example.com/story#section") -> True
        is_same_article_url("https://example.com/story",
                           "https://example.com/story?ref=home") -> True
        is_same_article_url("https://example.com/story1",
                           "https://example.com/story2") -> False
    """
    if not url1 or not url2:
        return False

    return normalize_url(url1) == normalize_url(url2)


def extract_base_url(url: str) -> Optional[str]:
    """
    Extract the base URL (scheme + netloc) from a URL.

    Args:
        url: The URL to extract base from

    Returns:
        Base URL or None if parsing fails

    Examples:
        extract_base_url("https://example.com/story?id=123")
            -> "https://example.com"
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return None
