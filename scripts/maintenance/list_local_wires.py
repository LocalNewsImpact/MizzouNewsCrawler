#!/usr/bin/env python3
"""Utility to list wire articles with local signals."""

from __future__ import annotations

import argparse
import json
from typing import Iterable, List, Optional

from dry_run_wire_audit import (
    fetch_articles,
    resolve_sqlite_path,
    WireAuditEngine,
)
from src.models.database import DatabaseManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "List articles flagged as wire that also have locality signals."
        )
    )
    parser.add_argument(
        "--database",
        default="sqlite:///data/mizzou.db",
        help="SQLAlchemy database URL (default: sqlite:///data/mizzou.db)",
    )
    parser.add_argument(
        "--domains",
        nargs="*",
        help="Optional domain hostnames to filter (e.g. example.com)",
    )
    parser.add_argument(
        "--status",
        nargs="*",
        default=["cleaned", "extracted", "wire"],
        help="Article statuses eligible for scanning",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of articles to inspect (0 for no limit)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a human-readable summary",
    )
    return parser.parse_args()


def collect_local_wires(
    database_url: str,
    domains: Optional[Iterable[str]],
    statuses: Iterable[str],
    limit: int,
) -> List[dict]:
    manager = DatabaseManager(database_url)
    try:
        articles = fetch_articles(manager, domains, statuses, limit)
        engine = WireAuditEngine(resolve_sqlite_path(database_url))
        locals_only = []
        for article in articles:
            result = engine.audit_article(article)
            if not (result.is_wire and result.is_local):
                continue
            locality = result.locality or {}
            locals_only.append(
                {
                    "id": article.id,
                    "domain": article.domain,
                    "status": article.status,
                    "provider": result.provider,
                    "existing_provider": result.existing_provider,
                    "local_confidence": locality.get("confidence"),
                    "local_signals": locality.get("signals", []),
                    "url": article.url,
                }
            )
        return locals_only
    finally:
        manager.close()


def print_human(locals_only: List[dict]) -> None:
    if not locals_only:
        print("No local wire articles found for the given filters.")
        return

    print(f"Found {len(locals_only)} local wire articles:\n")
    for item in locals_only:
        print(
            f"- {item['id']} | domain={item['domain']} | "
            f"provider={item['provider']}"
        )
        print(
            "  Status: {} | Existing provider: {}".format(
                item['status'],
                item['existing_provider'] or 'n/a',
            )
        )
        print(
            "  Locality: confidence={}; signals={}".format(
                item.get("local_confidence"),
                ", ".join(
                    f"{sig.get('type')}={sig.get('value')}"
                    for sig in item.get("local_signals", [])
                )
                or "(none)",
            )
        )
        print(f"  URL: {item['url']}\n")


def main() -> int:
    args = parse_args()
    locals_only = collect_local_wires(
        database_url=args.database,
        domains=args.domains,
        statuses=args.status,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(locals_only, indent=2))
    else:
        print_human(locals_only)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
