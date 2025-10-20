"""URL classification utilities for filtering non-article pages during discovery."""

import re
from urllib.parse import urlparse

# Patterns that strongly indicate a non-article page
NON_ARTICLE_PATTERNS = [
    # Gallery and multimedia pages
    r"/video-gallery/",
    r"/photo-gallery/",
    r"/photos/",
    r"/videos/",
    r"/galleries/",
    r"/gallery/",
    r"/slideshow",
    # Category and listing pages
    r"/category/",
    r"/tag/",
    r"/topics?/",
    r"/section/",
    r"/archive",
    r"/search",
    # Static/service pages
    r"/about",
    r"/contact",
    r"/staff",
    r"/advertise",
    r"/subscribe",
    r"/newsletter",
    r"/privacy",
    r"/terms",
    r"/sitemap",
    r"/rss",
    r"/feed",
    # Advertising and promotional pages
    r"/posterboard-ads/",
    r"/classifieds/",
    r"/marketplace/",
    r"/deals/",
    r"/coupons/",
    r"/promotions/",
    r"/sponsored/",
    # Technical pages
    r"\.pdf$",
    r"\.xml$",
    r"\.json$",
    r"/api/",
    r"/wp-admin",
    r"/wp-content",
    r"/wp-includes",
]

# Compile patterns for efficiency
COMPILED_NON_ARTICLE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in NON_ARTICLE_PATTERNS
]


def is_likely_article_url(url: str) -> bool:
    """Check if a URL is likely to be an article page.

    Returns False for obvious non-article pages like galleries, categories,
    static pages, etc. Returns True otherwise (may still be a false positive,
    but filters out the most obvious non-article patterns).

    Args:
        url: The URL to classify

    Returns:
        True if the URL might be an article, False if it's clearly not

    Examples:
        >>> is_likely_article_url("https://example.com/news/story-title")
        True
        >>> is_likely_article_url("https://example.com/video-gallery/news")
        False
        >>> is_likely_article_url("https://example.com/category/sports")
        False
    """
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Check against non-article patterns
        for pattern in COMPILED_NON_ARTICLE_PATTERNS:
            if pattern.search(path):
                return False

        return True

    except Exception:
        # If parsing fails, be conservative and allow it
        return True


def classify_url_batch(urls: list[str]) -> tuple[list[str], list[str]]:
    """Classify a batch of URLs into likely articles and non-articles.

    Args:
        urls: List of URLs to classify

    Returns:
        Tuple of (likely_articles, filtered_out)
    """
    likely_articles = []
    filtered_out = []

    for url in urls:
        if is_likely_article_url(url):
            likely_articles.append(url)
        else:
            filtered_out.append(url)

    return likely_articles, filtered_out
