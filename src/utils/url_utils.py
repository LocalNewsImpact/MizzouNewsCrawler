"""URL normalization utilities for consistent deduplication."""

import logging
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """
    Normalize a URL for consistent deduplication by:
    - Stripping www. prefix from hostname
    - Removing fragments and query parameters
    - Removing trailing slashes

    Note: Scheme (http/https) is preserved to avoid breaking sites that
    only support HTTP. For comparison, use is_same_article_url() which
    ignores scheme differences.

    Args:
        url: The URL to normalize

    Returns:
        Normalized URL

    Examples:
        normalize_url("http://www.example.com/story")
            -> "http://example.com/story"
        normalize_url("https://example.com/story#section")
            -> "https://example.com/story"
        normalize_url("https://www.example.com/story?ref=home")
            -> "https://example.com/story"
    """
    if not url or not url.strip():
        return url

    try:
        parsed = urlparse(url.strip())

        # Strip www. prefix from hostname
        netloc = parsed.netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Reconstruct URL without fragment and query parameters
        normalized = urlunparse(
            (
                parsed.scheme,  # Preserve original scheme
                netloc,
                parsed.path,
                parsed.params,  # Keep params (might be part of path structure)
                "",  # Remove query
                "",  # Remove fragment
            )
        )

        # Clean up any trailing slashes for consistency (except for root)
        if normalized.endswith("/") and len(normalized) > 1:
            # Only remove trailing slash if there's a path component
            if parsed.path and parsed.path != "/":
                normalized = normalized.rstrip("/")

        return normalized

    except Exception as e:
        logger.warning(f"Failed to normalize URL '{url}': {e}")
        return url  # Return original if parsing fails


def is_same_article_url(url1: str, url2: str) -> bool:
    """
    Check if two URLs represent the same article after normalization.

    Ignores scheme differences (http vs https) since they refer to the same resource.

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
        is_same_article_url("http://example.com/story",
                           "https://example.com/story") -> True
        is_same_article_url("https://example.com/story1",
                           "https://example.com/story2") -> False
    """
    if not url1 or not url2:
        return False

    norm1 = normalize_url(url1)
    norm2 = normalize_url(url2)

    # Strip scheme for comparison (http:// and https:// should match)
    norm1_no_scheme = norm1.split("://", 1)[1] if "://" in norm1 else norm1
    norm2_no_scheme = norm2.split("://", 1)[1] if "://" in norm2 else norm2

    return norm1_no_scheme == norm2_no_scheme


def normalize_url_for_dedup(url: str) -> str:
    """
    Normalize a URL for deduplication - strips scheme, www, query, fragment.

    Use this for checking if a URL already exists regardless of http/https.

    Args:
        url: The URL to normalize

    Returns:
        Scheme-agnostic normalized URL path (e.g., "example.com/story")
    """
    normalized = normalize_url(url)
    if "://" in normalized:
        return normalized.split("://", 1)[1]
    return normalized


def extract_base_url(url: str) -> str | None:
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
