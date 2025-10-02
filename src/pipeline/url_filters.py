import re

from storysniffer import StorySniffer


def check_is_article(url, discovery_method="unknown"):
    """Conservative article detection focusing on URL path structure patterns."""
    url_lower = (url or "").lower()

    non_article_patterns = [
        "/search",
        "/tag",
        "/category",
        "/author",
        "/rss",
        "/feed",
        "/sitemap",
        "/page/",
        "/contact",
        "/about",
        "/privacy",
        "/advertise",
        "/sections/",
        ".jpg",
        ".png",
        ".gif",
        ".pdf",
        ".css",
        ".js",
        ".xml",
    ]
    for pattern in non_article_patterns:
        if pattern in url_lower:
            return False

    if "/category/" in url_lower or "/tag/" in url_lower or "/topics/" in url_lower:
        return False

    if "/video" in url_lower or "/watch/" in url_lower or "/videos/" in url_lower:
        return False

    # Article-like patterns
    if re.search(r"/stories?/[^/]+", url_lower):
        return True

    date_patterns = [r"/\d{4}/\d{1,2}/\d{1,2}/", r"/\d{4}-\d{1,2}-\d{1,2}/"]
    for pattern in date_patterns:
        if re.search(pattern, url_lower):
            return True

    article_section_patterns = [
        r"/news/[^/]+",
        r"/articles?/[^/]+",
        r"/content/[^/]+",
        r"/posts?/[^/]+",
        r"/blog/[^/]+",
    ]
    for pattern in article_section_patterns:
        if re.search(pattern, url_lower):
            return True

    if re.search(r"/\d{3,}", url_lower):
        return True

    if discovery_method == "newspaper4k":
        path = url_lower.split("://")[-1].split("?")[0]
        segments = [seg for seg in (
            "/" + "/".join(path.split("/")[1:])).split("/") if seg]
        if len(segments) >= 2 or any("-" in seg for seg in segments):
            return True
        return False

    # Final fallback: try storysniffer if available
    try:
        sniffer = StorySniffer()
        return bool(sniffer.is_article_url(url))
    except Exception:
        return False
