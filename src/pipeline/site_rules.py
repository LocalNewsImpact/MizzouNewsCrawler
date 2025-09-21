"""Load host-specific parsing/skip rules from lookups/site_rules.csv.

Usage:
    from pipeline.site_rules import load_site_rules,
        get_rules_for_hostname
    rules = load_site_rules('lookups/site_rules.csv')
    host_rules = get_rules_for_hostname('www.kbia.org', rules)
"""

import csv
from pathlib import Path


def load_site_rules(path=None):
    path = Path(path or Path.cwd() / "lookups" / "site_rules.csv")
    if not path.exists():
        return {}

    rules = {}
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            hostname = row.get("hostname")
            if not hostname:
                continue

            # normalize empty strings to None
            normalized = {}
            for k, v in row.items():
                normalized[k] = v if (v and v.strip() != "") else None

            # parse lists for common columns
            sp = normalized.get("skip_patterns")
            if sp:
                normalized["skip_patterns"] = [
                    p.strip() for p in sp.split("|") if p.strip()
                ]

            cs = normalized.get("content_selector")
            if cs:
                normalized["content_selector"] = [
                    s.strip() for s in cs.split("|") if s.strip()
                ]

            # lightweight typed fields for improved rules
            normalized["preferred_method"] = normalized.get(
                "preferred_method"
            ) or normalized.get("extract_method")
            normalized["tags_selector"] = normalized.get("tags_selector")
            normalized["author_selector"] = normalized.get("author_selector")
            normalized["snapshot_example"] = normalized.get("snapshot_example")

            rules[hostname] = normalized

    return rules


def get_rules_for_hostname(hostname, rules):
    # exact match first
    if hostname in rules:
        return rules[hostname]

    # fallback to domain-only (strip subdomain)
    parts = hostname.split(".") if hostname else []
    if len(parts) > 2:
        domain = ".".join(parts[-2:])
        if domain in rules:
            return rules[domain]

    return None
