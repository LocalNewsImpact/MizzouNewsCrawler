#!/usr/bin/env python3
"""Dry-run audit for unlabeled wire-service articles.

Scans recent articles whose `wire` column lacks a provider entry and
emits detections without mutating the database. Detection heuristics
re-use existing wire indicators from the balanced cleaner and byline
cleaner so the results align with production logic.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from sqlalchemy import text

from src.models.database import DatabaseManager
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner
from src.utils.content_cleaning_telemetry import ContentCleaningTelemetry


@dataclass
class ArticleRecord:
    id: str
    url: str
    title: Optional[str]
    author: Optional[str]
    content: Optional[str]
    wire_raw: Optional[str]
    status: Optional[str]

    @property
    def domain(self) -> str:
        return urlparse(self.url).hostname or ""


@dataclass
class AuditResult:
    article: ArticleRecord
    provider: Optional[str]
    detected_provider: Optional[str]
    existing_provider: Optional[str]
    detection_methods: List[str]
    locality: Optional[Dict[str, Any]]
    source_context: Dict[str, Any]

    @property
    def is_wire(self) -> bool:
        return self.provider is not None

    @property
    def is_local(self) -> bool:
        return bool(self.locality and self.locality.get('is_local'))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run wire detection audit"
    )
    parser.add_argument(
        "--domains",
        nargs="*",
        help="Limit to these domain hostnames (e.g. example.com)",
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
        "--database",
        default="sqlite:///data/mizzou.db",
        help="SQLAlchemy database URL (default: sqlite:///data/mizzou.db)",
    )
    parser.add_argument(
        "--skip-labeled",
        action="store_true",
        help="Only report articles without an existing wire provider",
    )
    return parser.parse_args(argv)


def extract_provider_from_wire(wire_value: Optional[str]) -> Optional[str]:
    if not wire_value:
        return None

    value = wire_value.strip()
    if not value:
        return None

    if value.startswith("{"):
        try:
            parsed = json.loads(value)
            provider = parsed.get("provider")
            if isinstance(provider, str) and provider.strip():
                return provider.strip()
        except json.JSONDecodeError:
            return None
    else:
        # Treat plain provider strings as already labeled
        return value

    return None


def fetch_articles(
    db: DatabaseManager,
    domains: Optional[Iterable[str]],
    statuses: Iterable[str],
    limit: int,
) -> List[ArticleRecord]:
    filters: List[str] = []
    if domains:
        filters.append(
            "("
            + " OR ".join(
                "url LIKE :domain_{}".format(i) for i, _ in enumerate(domains)
            )
            + ")"
        )
    if statuses:
        filters.append(
            "status IN ("
            + ",".join(
                ":status_{}".format(i) for i, _ in enumerate(statuses)
            )
            + ")"
        )

    where_clause = " AND ".join(filters) if filters else "1=1"

    base_query = (
        """
        SELECT id, url, title, author, content, wire, status
        FROM articles
        WHERE {where_clause}
        ORDER BY created_at DESC
        """
    ).format(where_clause=where_clause)

    if limit and limit > 0:
        base_query += " LIMIT :limit"

    query = text(base_query)

    params: Dict[str, object] = {}
    if limit and limit > 0:
        params["limit"] = limit
    if domains:
        for i, domain in enumerate(domains):
            params[f"domain_{i}"] = f"%{domain}%"
    if statuses:
        for i, status in enumerate(statuses):
            params[f"status_{i}"] = status

    results = db.session.execute(query, params)
    return [ArticleRecord(*row) for row in results.fetchall()]


def resolve_sqlite_path(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "")
    if database_url.startswith("sqlite://"):
        return database_url.replace("sqlite://", "")
    return database_url


class WireAuditEngine:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.cleaner = BalancedBoundaryContentCleaner(
            db_path=db_path,
            enable_telemetry=False,
        )
        self.telemetry = ContentCleaningTelemetry(enable_telemetry=False)
        self._pattern_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _get_patterns_for_domain(self, domain: str) -> List[Dict[str, Any]]:
        if not domain:
            return []
        if domain not in self._pattern_cache:
            self._pattern_cache[domain] = (
                self.telemetry.get_persistent_patterns(domain)
            )
        return self._pattern_cache[domain]

    def audit_article(self, article: ArticleRecord) -> AuditResult:
        domain = article.domain
        existing_provider = extract_provider_from_wire(article.wire_raw)

        detection_methods: List[str] = []
        provider_candidates: List[Optional[str]] = []
        detected_provider: Optional[str] = None

        if existing_provider:
            detection_methods.append("existing_wire")
            provider_candidates.append(existing_provider)

        # Persistent pattern scan
        for pattern in self._get_patterns_for_domain(domain):
            pattern_text = pattern.get('text_content') or ''
            if not pattern_text:
                continue
            info = self.cleaner._detect_wire_service_in_pattern(
                pattern_text,
                domain,
            )
            if info:
                detected_provider = detected_provider or info.get('provider')
                method_tag = "persistent:{}".format(
                    pattern.get('pattern_type', 'unknown')
                )
                detection_methods.append(method_tag)
                provider_candidates.append(info.get('provider'))
                break

        # Byline detection
        detector = self.cleaner.wire_detector
        if article.author:
            detector._detected_wire_services = []
            if detector._is_wire_service(article.author):
                services = detector._detected_wire_services
                if services:
                    candidate = services[-1]
                    if not detector._is_wire_service_from_own_source(
                        candidate,
                        domain,
                    ):
                        detected_provider = detected_provider or candidate
                        detection_methods.append("byline")
                        provider_candidates.append(candidate)

        # Inline indicator detection
        inline = self.cleaner._detect_inline_wire_indicators(
            article.content or "",
            domain,
        )
        if inline:
            detected_provider = detected_provider or inline.get('provider')
            variant = inline.get('matched_variant') or 'unknown'
            detection_methods.append(f"inline:{variant}")
            provider_candidates.append(inline.get('provider'))

        # Determine final provider preference
        provider = next((p for p in provider_candidates if p), None)

        locality: Optional[Dict[str, Any]] = None
        source_context: Dict[str, Any] = {}

        if provider and article.content:
            source_context = self.cleaner._get_article_source_context(
                article.id
            )
            locality = self.cleaner._assess_locality(
                article.content,
                source_context,
                domain,
            )

        return AuditResult(
            article=article,
            provider=provider,
            detected_provider=detected_provider,
            existing_provider=existing_provider,
            detection_methods=detection_methods,
            locality=locality,
            source_context=source_context,
        )


def format_locality_summary(locality: Optional[Dict[str, Any]]) -> str:
    if not locality:
        return "n/a"
    parts = [
        f"is_local={bool(locality.get('is_local'))}",
        f"confidence={locality.get('confidence')}",
    ]
    signals = locality.get('signals') or []
    if signals:
        sample = ", ".join(
            f"{sig.get('type')}:{sig.get('value')}"
            for sig in signals[:3]
        )
        parts.append(f"signals=[{sample}{'…' if len(signals) > 3 else ''}]")
    return "; ".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    with DatabaseManager(args.database) as db:
        articles = fetch_articles(db, args.domains, args.status, args.limit)

    if not articles:
        print("No articles matched the provided filters.")
        return 0

    engine = WireAuditEngine(resolve_sqlite_path(args.database))

    results: List[AuditResult] = [
        engine.audit_article(article)
        for article in articles
    ]
    wire_results = [res for res in results if res.is_wire]
    new_wire_results = [
        res for res in wire_results if not res.existing_provider
    ]
    local_wire_results = [res for res in wire_results if res.is_local]
    new_local_results = [
        res for res in local_wire_results if not res.existing_provider
    ]

    print("=== Wire Detection Summary ===")
    print(f"Articles examined: {len(articles)}")
    print(f"Articles flagged as wire: {len(wire_results)}")
    print(f"  Already labeled: {len(wire_results) - len(new_wire_results)}")
    print(f"  Newly detected: {len(new_wire_results)}")
    print(f"Local wire candidates: {len(local_wire_results)}")
    print(f"  Newly detected local: {len(new_local_results)}")

    domain_totals: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"wire": 0, "local": 0}
    )
    for res in wire_results:
        domain_totals[res.article.domain]["wire"] += 1
        if res.is_local:
            domain_totals[res.article.domain]["local"] += 1

    if domain_totals:
        print("\nPer-domain breakdown:")
        for domain, counts in sorted(domain_totals.items()):
            print(
                f"  {domain}: wire={counts['wire']}, local={counts['local']}"
            )

    reportable_results = wire_results
    if args.skip_labeled:
        reportable_results = [
            res for res in wire_results if not res.existing_provider
        ]

    if reportable_results:
        print("\nDetailed wire listings:\n")
        for res in reportable_results:
            locality_summary = format_locality_summary(res.locality)
            detection_summary = ",".join(res.detection_methods) or "(none)"
            provider_label = res.provider or "unknown"
            status = res.article.status or "unknown"
            print(
                "- {} | domain={} | status={}".format(
                    res.article.id,
                    res.article.domain,
                    status,
                )
            )
            print(f"  Provider: {provider_label}")
            print(f"  Existing provider: {res.existing_provider or 'n/a'}")
            print(f"  Detection methods: {detection_summary}")
            print(f"  Locality: {locality_summary}")
            print(f"  URL: {res.article.url}")
            print()

    if not wire_results:
        print("No wire indicators were found for the examined articles.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
