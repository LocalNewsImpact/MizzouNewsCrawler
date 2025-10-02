"""pipeline/extractors.py
Small extractor registry with host-config-driven selectors and fallback chain.
Returns normalized dicts: {title, byline, date, text, html, lead_image}
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# newspaper is optional but used as a useful fallback
try:
    from newspaper import Article
except Exception:
    Article = None

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(
        os.path.dirname(__file__)),
        "sources",
         "host_selectors.json")


class HostSelector:
    def __init__(self, cfg: Dict[str, Any]):
        self.host = cfg.get("host")
        self.selectors = cfg.get("selectors", {})
        # selectors may be a comma-separated string in config; normalize to
        # list
        for k, v in list(self.selectors.items()):
            if isinstance(v, str) and "," in v:
                self.selectors[k] = [s.strip()
                                             for s in v.split(",") if s.strip()]

    def extract_with_selectors(
            self, soup: BeautifulSoup) -> Dict[str, Optional[str]]:
        out = {
            "title": None,
            "byline": None,
            "date": None,
            "text": None,
            "html": None,
            "lead_image": None,
        }
        out["html"] = str(soup)
        # title
        tit = self.selectors.get("title")
        if tit:
            for sel in tit if isinstance(tit, list) else [tit]:
                node = soup.select_one(sel)
                if node and node.get_text(strip=True):
                    out["title"] = node.get_text(" ", strip=True)
                    break
        # byline
        by = self.selectors.get("byline")
        if by:
            for sel in by if isinstance(by, list) else [by]:
                node = soup.select_one(sel)
                if node and node.get_text(strip=True):
                    out["byline"] = node.get_text(" ", strip=True)
                    break
        # date
        dt = self.selectors.get("date")
        if dt:
            for sel in dt if isinstance(dt, list) else [dt]:
                node = soup.select_one(sel)
                if node and node.get("datetime"):
                    out["date"] = node.get("datetime")
                    break
                if node and node.get_text(strip=True):
                    out["date"] = node.get_text(" ", strip=True)
                    break
        # article body
        art = self.selectors.get("article")
        if art:
            for sel in art if isinstance(art, list) else [art]:
                node = soup.select_one(sel)
                if node and node.get_text(strip=True):
                    out["text"] = node.get_text(" ", strip=True)
                    break
        # lead image (allow selector to be a list or a single selector)
        img = self.selectors.get("lead_image")
        if img:
            for sel in img if isinstance(img, list) else [img]:
                node = soup.select_one(sel)
                if not node:
                    continue
                # common patterns: <img src=> or <meta property="og:image"
                # content=>
                if node.get("src"):
                    out["lead_image"] = node.get("src")
                    break
                if node.name == "meta" and node.get("content"):
                    out["lead_image"] = node.get("content")
                    break
        return out


class ExtractorRegistry:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.host_map: Dict[str, HostSelector] = {}
        self._load_config()

    def _load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            data = []
        except Exception:
            data = []
        for entry in data:
            host = entry.get("host")
            if host:
                self.host_map[host] = HostSelector(entry)

    def get(self, hostname: str):
        return self.host_map.get(hostname)


def extract_schemaorg(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    # find <script type="application/ld+json">
    scripts = soup.find_all("script", type="application/ld+json")
    for s in scripts:
        try:
            payload = json.loads(s.string or "{}")
        except Exception:
            # sometimes multiple JSON objects or leading/trailing text; try to
            # salvage
            txt = (s.string or "").strip()
            try:
                # find first { ... }
                m = re.search(r"\{.*\}", txt, flags=re.S)
                if m:
                    payload = json.loads(m.group(0))
                else:
                    continue
            except Exception:
                continue
        # payload can be dict or list
        if isinstance(payload, list):
            for item in payload:
                if item.get("@type", "").lower() in ("newsarticle", "article"):
                    return {
                        "title": item.get("headline") or item.get("name"),
                        "byline": item.get("author")
                        and (
                            item.get("author").get("name")
                            if isinstance(item.get("author"), dict)
                            else None
                        ),
                        "date": item.get("datePublished"),
                        "text": item.get("articleBody"),
                        "lead_image": _lead_image_field(item.get("image")),
                        "html": None,
                    }
        elif isinstance(payload, dict):
            if payload.get("@type", "").lower() in ("newsarticle", "article"):
                return {
                    "title": payload.get("headline") or payload.get("name"),
                    "byline": payload.get("author")
                    and (
                        payload.get("author").get("name")
                        if isinstance(payload.get("author"), dict)
                        else None
                    ),
                    "date": payload.get("datePublished"),
                    "text": payload.get("articleBody"),
                    "lead_image": _lead_image_field(payload.get("image")),
                    "html": None,
                }
    return None


def newspaper_fallback(url: str) -> Optional[Dict[str, Any]]:
    if Article is None:
        return None
    try:
        a = Article(url)
        a.download()
        a.parse()
        return {
            "title": a.title or None,
            "byline": getattr(
                a,
                "authors",
                None) and ", ".join(
                a.authors) or None,
            "date": a.publish_date and a.publish_date.isoformat() or None,
            "text": a.text or None,
            "html": a.html or None,
            "lead_image": a.top_image or None,
             }
    except Exception:
        return None


def normalize_text(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    # collapse whitespace
    txt = re.sub(r"\s+", " ", t).strip()
    return txt


def _lead_image_field(field: Any) -> Optional[str]:
    """Normalize schema.org image field which may be a string, dict, or list.

    Returns a string URL if found, otherwise None.
    """
    if not field:
        return None
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return field.get("url") or field.get("src") or None
    if isinstance(field, list):
        for item in field:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                v = item.get("url") or item.get("src")
                if v:
                    return v
    return None


DEFAULT_SELECTORS = [
    "article",
    "[role=main]",
    ".article-body",
    ".entry-content",
    ".post-content",
]


def extract(html: str,
    url: Optional[str] = None,
    registry: Optional[ExtractorRegistry] = None) -> Dict[str,
     Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    hostname = None
    if url:
        try:
            hostname = urlparse(url).hostname
        except Exception:
            hostname = None
    # 1) schema.org
    schema = extract_schemaorg(soup)
    if schema and schema.get("text"):
        return {k: normalize_text(v) if isinstance(
            v, str) else v for k, v in schema.items()}
    # 2) host-specific selectors
    if registry and hostname:
        hs = registry.get(hostname)
        if hs:
            res = hs.extract_with_selectors(soup)
            if res.get("text"):
                return {
                    k: normalize_text(v) if isinstance(v, str) else v
                    for k, v in res.items()
                }
    # 3) newspaper fallback (requires network access; try if url present)
    if url:
        nw = newspaper_fallback(url)
        if nw and nw.get("text"):
            return {k: normalize_text(v) if isinstance(
                v, str) else v for k, v in nw.items()}
    # 4) generic selectors
    for sel in DEFAULT_SELECTORS:
        node = soup.select_one(sel)
        if node and node.get_text(strip=True):
            out = {
                "title": None,
                "byline": None,
                "date": None,
                "text": node.get_text(" ", strip=True),
                "html": str(node),
                "lead_image": None,
            }
            return {
                k: normalize_text(v) if isinstance(v, str) else v
                for k, v in out.items()
            }
    # 5) text-only fallback
    txt = soup.get_text(" ", strip=True)
    return {
        "title": None,
        "byline": None,
        "date": None,
        "text": normalize_text(txt),
        "html": html,
        "lead_image": None,
    }


if __name__ == "__main__":
    # quick local smoke test
    reg = ExtractorRegistry()
    print("Loaded hosts:", list(reg.host_map.keys()))
