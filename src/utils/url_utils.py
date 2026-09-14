"""URL normalization utilities for consistent deduplication."""

import logging
import re
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


#: A front controller in the path, which is routing rather than address.
#: A CMS that serves `/index.php/news/x` serves the identical page at
#: `/news/x`, and different parts of the same site link to each form --
#: so discovery found both, made two links, and the story was fetched,
#: parsed and classified twice.
#:
#: 313 stories were in the corpus twice on 2026-09-14, 278 of them
#: extracted twice, 99% of them from two publishers:
#: richmond-dailynews.com (169) and excelsiorspringsstandard.com (139).
#:
#: `/index.php` alone becomes `/` -- that is the site's front page, which
#: is what the bare domain serves too.
_FRONT_CONTROLLER = re.compile(r"/index\.(php|html?|cfm|asp|aspx|jsp)(?=/|$)", re.I)


def normalize_url(url: str) -> str:
    """
    Normalize a URL for consistent storage by:
    - Removing fragments and query parameters
    - Removing a front-controller segment (/index.php and its kin)
    - Removing trailing slashes

    Note: Scheme (http/https) and subdomain (www.) are preserved.
    For deduplication comparison, use normalize_url_for_dedup() or
    is_same_article_url() which ignore scheme and www differences.

    Args:
        url: The URL to normalize

    Returns:
        Normalized URL

    Examples:
        normalize_url("https://www.example.com/story#section")
            -> "https://www.example.com/story"
        normalize_url("https://www.example.com/story?ref=home")
            -> "https://www.example.com/story"
    """
    if not url or not url.strip():
        return url

    try:
        parsed = urlparse(url.strip())

        # Keep hostname as-is (including www. if present)
        # Subdomain stripping is done only in dedup functions for comparison
        netloc = parsed.netloc

        # Reconstruct URL without fragment and query parameters
        normalized = urlunparse(
            (
                parsed.scheme,  # Preserve original scheme
                netloc,
                # `/index.php/news/x` and `/news/x` are one page, and
                # storing both is how one story became two records.
                # No `or "/"` fallback: an empty path must stay empty.
                # Defaulting it turned `https://example.com` into
                # `https://example.com/`, which is a different string for
                # every caller that compares them.
                _FRONT_CONTROLLER.sub("", parsed.path),
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

    # Strip www. prefix for comparison (www.example.com and example.com should match)
    if norm1_no_scheme.startswith("www."):
        norm1_no_scheme = norm1_no_scheme[4:]
    if norm2_no_scheme.startswith("www."):
        norm2_no_scheme = norm2_no_scheme[4:]

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
        path = normalized.split("://", 1)[1]
    else:
        path = normalized

    # Strip www. prefix for dedup comparison only
    if path.startswith("www."):
        path = path[4:]

    return path


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
