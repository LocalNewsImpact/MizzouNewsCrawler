"""Archive raw page HTML to GCS so extractors can be compared on identical input.

Extraction quality work repeatedly hits the same wall: the only way to know
whether extractor A beats extractor B on a given page is to run both against
the *same* bytes. Re-fetching the URL later is not equivalent — the page may
have changed, and bot-protected sites return challenge pages to naive
requests, so a re-fetch comparison measures the proxy stack rather than the
extractor.

This module stores the HTML that produced each article, keyed by article id,
so a candidate extractor can be replayed offline against the exact input
production saw. Objects are deleted after 30 days by a bucket lifecycle rule
(see ``docs/raw-html-archive.md``); nothing here deletes anything, so a
retention change is a bucket-config change, not a code change.

Every failure path is soft: archiving is observability, and it must never
cost us an article. Callers get ``None`` and carry on.
"""

from __future__ import annotations

import gzip
import logging
import os
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "mizzou-news-crawler-raw-html"

# Pages beyond this are almost always non-articles (asset dumps, infinite
# scroll archives). Skipping them keeps one pathological page from dominating
# storage; the article row is still written, just without a raw_gcs_path.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024

_client = None
_client_failed = False
_lock = threading.Lock()


def _enabled() -> bool:
    return os.getenv("RAW_HTML_ARCHIVE_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _bucket_name() -> str:
    return os.getenv("RAW_HTML_BUCKET", DEFAULT_BUCKET)


def _max_bytes() -> int:
    try:
        return int(os.getenv("RAW_HTML_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    except ValueError:
        return DEFAULT_MAX_BYTES


def _get_client():
    """Return a cached GCS client, or None if unavailable.

    A failed init is remembered so environments without credentials (local
    dev, CI, tests) log once instead of on every article.
    """
    global _client, _client_failed

    if _client is not None or _client_failed:
        return _client

    with _lock:
        if _client is not None or _client_failed:
            return _client
        try:
            from google.cloud import storage

            _client = storage.Client()
        except Exception as exc:
            _client_failed = True
            logger.info(
                "Raw HTML archiving disabled (no GCS client: %s: %s)",
                type(exc).__name__,
                exc,
            )
    return _client


def build_object_path(url: str, article_id: str, when: datetime | None = None) -> str:
    """Build the object path for an article's HTML.

    Date-partitioned first so the lifecycle rule's effect is legible when
    browsing the bucket, then by host so a per-publisher replay is a prefix
    listing rather than a full scan.
    """
    when = when or datetime.now(timezone.utc)
    host = (urlparse(url).netloc or "unknown").lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{when:%Y/%m/%d}/{host or 'unknown'}/{article_id}.html.gz"


def archive_html(
    url: str,
    html: str | bytes | None,
    article_id: str,
    extraction_method: str | None = None,
) -> str | None:
    """Store ``html`` and return its ``gs://`` URI, or None if not stored.

    Returns None (never raises) when archiving is disabled, the payload is
    empty or oversized, or GCS is unreachable.
    """
    if not html or not _enabled():
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        payload = (
            html.encode("utf-8", errors="replace") if isinstance(html, str) else html
        )

        limit = _max_bytes()
        if len(payload) > limit:
            logger.debug(
                "Skipping raw HTML archive for %s: %d bytes exceeds %d",
                url,
                len(payload),
                limit,
            )
            return None

        path = build_object_path(url, article_id)
        blob = client.bucket(_bucket_name()).blob(path)

        # Stored as a .html.gz object rather than a gzip-encoded .html one:
        # GCS decompressively transcodes objects tagged Content-Encoding:gzip
        # on download, which would silently hand replay tooling a different
        # byte stream than we uploaded.
        blob.content_type = "application/gzip"
        if extraction_method:
            blob.metadata = {"extraction_method": extraction_method, "source_url": url}

        blob.upload_from_string(gzip.compress(payload), content_type="application/gzip")

        return f"gs://{_bucket_name()}/{path}"

    except Exception as exc:
        logger.warning(
            "Raw HTML archive failed for %s: %s: %s", url, type(exc).__name__, exc
        )
        return None


def fetch_html(gcs_uri: str) -> str | None:
    """Read back an archived page. Used by offline extractor A/B tooling."""
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        bucket_name, _, path = gcs_uri[len("gs://") :].partition("/")
        blob = client.bucket(bucket_name).blob(path)
        return gzip.decompress(blob.download_as_bytes()).decode(
            "utf-8", errors="replace"
        )
    except Exception as exc:
        logger.warning(
            "Raw HTML fetch failed for %s: %s: %s", gcs_uri, type(exc).__name__, exc
        )
        return None


def reset_client_cache() -> None:
    """Drop the cached client. For tests."""
    global _client, _client_failed
    with _lock:
        _client = None
        _client_failed = False
