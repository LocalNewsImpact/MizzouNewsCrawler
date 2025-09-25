"""Shared crawler helpers for discovery, fetching, filtering and persistence.

This module centralizes the small crawler used by scripts and notebooks so
both can import the same behavior and produce consistent `data/raw` JSON
artifacts.
"""

import json
import os
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from dateutil import parser as dateparser

from .io_utils import atomic_write_json


def is_valid(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


def get_news_urls(seed_url: str):
    domain_name = urlparse(seed_url).netloc
    internal_urls = set()
    external_urls = set()
    try:
        resp = requests.get(
            seed_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        soup = BeautifulSoup(resp.content, "html.parser")
    except Exception:
        return []

    for a_tag in soup.find_all("a"):
        href = a_tag.get("href")
        if not href:
            continue
        href = urljoin(seed_url, href)
        parsed_href = urlparse(href)
        href = parsed_href.scheme + "://" + parsed_href.netloc + parsed_href.path
        if not is_valid(href):
            continue
        if domain_name not in href:
            external_urls.add(href)
            continue
        if href in internal_urls:
            continue
        internal_urls.add(href)

    return sorted(internal_urls)


def crawl_page(url: str) -> str:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if resp.ok:
            return resp.text
    except Exception:
        return ""
    return ""


def filter_site_url(u: str) -> bool:
    # Simple generic filter: skip known non-article paths and require a date
    # Skip clearly non-article sections, but do NOT require dates in the URL.
    if ("/show" in u) or ("/podcast" in u) or ("paul-pepper" in u):
        return False
    return True


def extract_published_date(html: str):
    """Try several heuristics to extract a publication datetime from HTML.

    Returns an ISO 8601 string (UTC naive) or None if not found.
    """
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    # 1) JSON-LD script with datePublished
    try:
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                j = json.loads(s.string or "{}")
            except Exception:
                continue
            # j can be a list or dict
            if isinstance(j, list):
                items = j
            else:
                items = [j]
            for item in items:
                if not isinstance(item, dict):
                    continue
                dp = item.get("datePublished") or item.get("dateCreated")
                if not dp:
                    continue
                # normalize dp which may be list or dict
                if isinstance(dp, (list, tuple)):
                    dp = dp[0] if dp else None
                if isinstance(dp, dict):
                    # try common keys
                    dp = dp.get("@value") or dp.get("value") or str(dp)
                if not dp:
                    continue
                try:
                    return str(dateparser.parse(str(dp)))
                except Exception:
                    continue
    except Exception:
        pass

    # 2) common meta tags
    meta_names = [
        ("property", "article:published_time"),
        ("name", "pubdate"),
        ("name", "publishdate"),
        ("name", "date"),
        ("itemprop", "datePublished"),
    ]
    for attr, val in meta_names:
        tag = soup.find("meta", attrs={attr: val})
        if tag is None:
            continue
        content = None
        # ensure tag is a Tag before calling .get
        if isinstance(tag, Tag):
            content = tag.get("content")
        if not content:
            continue
        # normalize
        if isinstance(content, (list, tuple)):
            content = content[0] if content else None
        try:
            return str(dateparser.parse(str(content)))
        except Exception:
            pass

    # 3) <time datetime=>
    t = soup.find("time")
    if t is not None:
        dt = None
        if isinstance(t, Tag):
            dt = t.get("datetime")
        if not dt:
            dt = t.get_text() if isinstance(t, Tag) else None
        if dt:
            # normalize
            if isinstance(dt, (list, tuple)):
                dt = dt[0] if dt else None
            try:
                return str(dateparser.parse(str(dt)))
            except Exception:
                pass

    return None


def write_site_json(news_data, out_dir="data/raw") -> str:
    """Atomically write a per-site JSON file and return the final path.

    Uses `pipeline.io_utils.atomic_write_json` to avoid partially written
    files being visible to downstream processes.
    """
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    out_path = os.path.join(out_dir, f"site_{timestamp}.json")
    atomic_write_json(news_data, out_path, ensure_ascii=False)
    return out_path
