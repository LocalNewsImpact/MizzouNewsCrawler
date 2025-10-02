"""
Small helper to load per-site specs and decide whether a URL should be skipped.

Design notes:
- Loads `lookups/site_specs.csv` (hostname, skip_patterns,
    force_include_patterns).
- skip_patterns/force_include_patterns are semicolon-separated tokens.
    Token syntax:
    - literal substring -> skip if substring in url
    - not-<substring> -> skip if substring NOT in url
    - endswith:<suffix> -> skip if url endswith(suffix)
    - contains:<substr> -> same as literal
    - regex:<pattern> -> skip if re.search(pattern, url)
- force_include_patterns uses same syntax and can override a skip.

This is intentionally conservative and easy to extend.
"""

from __future__ import annotations

import csv
import os
import re

LOOKUPS_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "lookups", "site_specs.csv"
)


def load_site_specs(
    csv_path: str | None = None,
) -> dict[str, dict[str, list[str]]]:
    """Load the CSV into a dict keyed by hostname.

    Returns a mapping: { host: { 'skip_patterns': [...],
    'force_include_patterns': [...] } }
    """
    path = csv_path or LOOKUPS_DEFAULT
    specs: dict[str, dict[str, list[str]]] = {}
    # prefer sqlite store when available
    try:
        from web import sqlite_store

        conn = sqlite_store.get_conn()
        cur = conn.execute("SELECT * FROM site_specs")
        for r in cur.fetchall():
            host = r.get("domain") or ""
            if not host:
                continue
            skip_raw = r.get("skip_patterns") or ""
            force_raw = r.get("force_include_patterns") or ""
            skip = [t.strip() for t in skip_raw.split(";") if t.strip()]
            force = [t.strip() for t in force_raw.split(";") if t.strip()]
            specs[host] = {
                "skip_patterns": skip,
                "force_include_patterns": force,
            }
        conn.close()
        if specs:
            return specs
    except Exception:
        # fall back to CSV
        pass

    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                host = (
                    row.get("hostname") or row.get("host") or row.get("name") or ""
                ).strip()
                if not host:
                    continue
                skip_raw = row.get("skip_patterns", "") or ""
                force_raw = row.get("force_include_patterns", "") or ""
                skip = [t.strip() for t in skip_raw.split(";") if t.strip()]
                force = [t.strip() for t in force_raw.split(";") if t.strip()]
                specs[host] = {
                    "skip_patterns": skip,
                    "force_include_patterns": force,
                }
    except FileNotFoundError:
        # No CSV yet — return empty mapping
        return {}
    return specs


def _match_token(token: str, url: str) -> bool:
    """Return True if token matches the url according to our mini-language."""
    if token.startswith("not-"):
        subj = token[len("not-") :]
        # treat remaining as plain substring unless it uses special prefixes
        return subj not in url
    if token.startswith("endswith:"):
        return url.endswith(token.split(":", 1)[1])
    if token.startswith("contains:"):
        return token.split(":", 1)[1] in url
    if token.startswith("regex:"):
        try:
            return re.search(token.split(":", 1)[1], url) is not None
        except re.error:
            return False
    # default: substring
    return token in url


def should_skip(url: str, specs: dict[str, dict[str, list[str]]]) -> bool:
    """Decide whether a URL should be skipped using per-host specs.

    Logic:
    - Look up host in specs (exact match). If missing, no host-specific skips.
    - If any skip_pattern token matches -> candidate_skip = True
    - If any force_include_pattern matches -> candidate_skip = False (override)
    - Return candidate_skip
    """
    try:
        host = re.sub(r"://", "://", url).split("://", 1)[1].split("/", 1)[0]
    except Exception:
        host = ""

    host_spec = specs.get(host)
    if not host_spec:
        return False

    skip_tokens = host_spec.get("skip_patterns", [])
    force_tokens = host_spec.get("force_include_patterns", [])

    # If any force pattern matches, never skip
    for t in force_tokens:
        if _match_token(t, url):
            return False

    # If any skip token matches, skip
    for t in skip_tokens:
        if _match_token(t, url):
            return True

    return False


if __name__ == "__main__":
    # simple CLI for debugging
    import sys

    specs = load_site_specs()
    if len(sys.argv) > 1:
        for u in sys.argv[1:]:
            print(u, "->", "SKIP" if should_skip(u, specs) else "KEEP")
    else:
        print("Usage: python -m pipeline.site_filters <url>...")
