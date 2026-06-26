#!/usr/bin/env python3
"""
Test new structured metadata wire detector against labeled articles in production.

This script runs inside a production pod and tests the NEW detection logic
(JSON-LD author, canonical cross-domain, OG distributor, meta author, dataLayer)
against articles currently marked as 'labeled' to find potential wire articles
that weren't detected.

Usage (run from local):
    # Copy script to pod
    kubectl cp test_new_detector_production.py production/$(kubectl get pods -n production -l app=mizzou-processor -o jsonpath='{.items[0].metadata.name}'):/tmp/
    
    # Run and capture output
    kubectl exec -n production deployment/mizzou-processor -- python /tmp/test_new_detector_production.py > new_detector_results.csv

The script outputs CSV to stdout which can be redirected locally.
"""

import csv
import json
import re
import sys
from datetime import datetime
from typing import Any

from sqlalchemy import text

from src.models.database import DatabaseManager


def get_wire_patterns_from_db(session) -> dict:
    """Load all wire patterns from production DB, grouped by type."""
    result = session.execute(text("""
        SELECT service_name, pattern, pattern_type, case_sensitive, priority
        FROM wire_services
        WHERE active = true
        ORDER BY priority DESC, service_name
    """))
    
    patterns = {"url": [], "author": [], "content": []}
    for row in result:
        pattern_type = row.pattern_type
        if pattern_type in patterns:
            patterns[pattern_type].append({
                "service_name": row.service_name,
                "pattern": row.pattern,
                "case_sensitive": row.case_sensitive,
                "priority": row.priority,
            })
    
    return patterns


def match_pattern(text_to_match: str, pattern_info: dict) -> tuple[bool, str | None]:
    """Try to match a pattern against text, return (matched, service_name)."""
    if not text_to_match:
        return False, None
    
    pattern = pattern_info["pattern"]
    case_sensitive = pattern_info["case_sensitive"]
    
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        if re.search(pattern, text_to_match, flags):
            return True, pattern_info["service_name"]
    except re.error:
        pass
    
    return False, None


def detect_canonical_cross_domain(metadata: dict, article_url: str) -> dict | None:
    """Check if canonical URL points to a different domain (syndication signal)."""
    canonical = metadata.get("canonical_url") or metadata.get("og_url")
    if not canonical:
        return None
    
    from urllib.parse import urlparse
    
    try:
        article_host = urlparse(article_url).netloc.lower().replace("www.", "")
        canonical_host = urlparse(canonical).netloc.lower().replace("www.", "")
        
        if article_host and canonical_host and article_host != canonical_host:
            # Cross-domain canonical - strong syndication signal
            return {
                "detected_by": "canonical_cross_domain",
                "evidence": f"canonical={canonical_host}, article={article_host}",
                "canonical_url": canonical,
            }
    except Exception:
        pass
    
    return None


def detect_og_distributor(metadata: dict) -> dict | None:
    """Check for OG distributor_category tag indicating wire content."""
    distributor = metadata.get("og_distributor_category") or metadata.get("distributor_category")
    if distributor and "wire" in str(distributor).lower():
        return {
            "detected_by": "og_distributor_category",
            "evidence": f"distributor_category={distributor}",
        }
    return None


def detect_jsonld_author(metadata: dict, author_patterns: list) -> dict | None:
    """Check JSON-LD author field against DB patterns."""
    # Try various places where JSON-LD author might be stored
    jsonld = metadata.get("jsonld") or metadata.get("json_ld") or {}
    if isinstance(jsonld, str):
        try:
            jsonld = json.loads(jsonld)
        except json.JSONDecodeError:
            jsonld = {}
    
    # Handle list of JSON-LD objects
    if isinstance(jsonld, list):
        for item in jsonld:
            result = _check_jsonld_item_for_author(item, author_patterns)
            if result:
                return result
    elif isinstance(jsonld, dict):
        result = _check_jsonld_item_for_author(jsonld, author_patterns)
        if result:
            return result
    
    return None


def _check_jsonld_item_for_author(item: dict, author_patterns: list) -> dict | None:
    """Check a single JSON-LD item for author wire patterns."""
    if not isinstance(item, dict):
        return None
    
    # Get author field
    author = item.get("author")
    if not author:
        return None
    
    # Normalize to list
    if isinstance(author, dict):
        authors = [author]
    elif isinstance(author, list):
        authors = author
    else:
        authors = [{"name": str(author)}]
    
    for auth in authors:
        if isinstance(auth, dict):
            name = auth.get("name", "")
        else:
            name = str(auth)
        
        if not name:
            continue
        
        # Check against DB patterns
        for pattern_info in author_patterns:
            matched, service = match_pattern(name, pattern_info)
            if matched:
                return {
                    "detected_by": "jsonld_author",
                    "wire_service": service,
                    "evidence": f"JSON-LD author.name='{name}' matched pattern",
                }
    
    return None


def detect_meta_author(metadata: dict, author_patterns: list) -> dict | None:
    """Check meta author tag against DB patterns."""
    meta_author = metadata.get("meta_author") or metadata.get("author")
    if not meta_author:
        return None
    
    if isinstance(meta_author, list):
        meta_author = ", ".join(str(a) for a in meta_author)
    else:
        meta_author = str(meta_author)
    
    for pattern_info in author_patterns:
        matched, service = match_pattern(meta_author, pattern_info)
        if matched:
            return {
                "detected_by": "meta_author",
                "wire_service": service,
                "evidence": f"meta author='{meta_author[:100]}' matched pattern",
            }
    
    return None


def detect_jsonld_syndication(metadata: dict) -> dict | None:
    """Check JSON-LD for isBasedOn or mainEntityOfPage pointing to wire domains."""
    jsonld = metadata.get("jsonld") or metadata.get("json_ld") or {}
    if isinstance(jsonld, str):
        try:
            jsonld = json.loads(jsonld)
        except json.JSONDecodeError:
            return None
    
    wire_domains = [
        "apnews.com", "reuters.com", "afp.com", "upi.com",
        "apimages.com", "ap.org", "reutersagency.com"
    ]
    
    items = jsonld if isinstance(jsonld, list) else [jsonld]
    
    for item in items:
        if not isinstance(item, dict):
            continue
        
        # Check isBasedOn
        is_based_on = item.get("isBasedOn")
        if is_based_on:
            url = is_based_on if isinstance(is_based_on, str) else is_based_on.get("url", "")
            for domain in wire_domains:
                if domain in url.lower():
                    return {
                        "detected_by": "jsonld_isBasedOn",
                        "evidence": f"isBasedOn points to {domain}",
                    }
        
        # Check mainEntityOfPage
        main_entity = item.get("mainEntityOfPage")
        if main_entity:
            url = main_entity if isinstance(main_entity, str) else main_entity.get("@id", "")
            for domain in wire_domains:
                if domain in url.lower():
                    return {
                        "detected_by": "jsonld_mainEntityOfPage",
                        "evidence": f"mainEntityOfPage points to {domain}",
                    }
    
    return None


def detect_datalayer_syndication(metadata: dict) -> dict | None:
    """Check for dataLayer syndication flags."""
    datalayer = metadata.get("dataLayer") or metadata.get("datalayer") or {}
    if isinstance(datalayer, str):
        try:
            datalayer = json.loads(datalayer)
        except json.JSONDecodeError:
            return None
    
    if not isinstance(datalayer, dict):
        return None
    
    # Check common syndication flags
    if datalayer.get("isWire") or datalayer.get("is_wire"):
        return {
            "detected_by": "dataLayer_isWire",
            "evidence": "dataLayer.isWire=true",
        }
    
    if datalayer.get("isSyndicated") or datalayer.get("is_syndicated"):
        return {
            "detected_by": "dataLayer_isSyndicated",
            "evidence": "dataLayer.isSyndicated=true",
        }
    
    content_type = datalayer.get("contentType") or datalayer.get("content_type", "")
    if "wire" in str(content_type).lower():
        return {
            "detected_by": "dataLayer_contentType",
            "evidence": f"dataLayer.contentType='{content_type}'",
        }
    
    return None


def run_new_detection(article: dict, patterns: dict) -> dict | None:
    """
    Run the NEW detection logic against an article.
    Returns detection result or None if not detected as wire.
    
    Checks:
    1. Direct author field against DB author patterns
    2. Metadata wire_hints (if present from crawler)
    3. Canonical cross-domain
    4. OG distributor
    5. JSON-LD author
    6. JSON-LD syndication signals
    7. Meta author
    8. dataLayer syndication
    """
    metadata = article.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    
    url = article.get("url", "")
    author_patterns = patterns.get("author", [])
    
    # FIRST: Check direct author field against DB patterns
    # This is the most reliable check since author is always stored
    direct_author = article.get("author") or ""
    if direct_author:
        for pattern_info in author_patterns:
            matched, service = match_pattern(direct_author, pattern_info)
            if matched:
                return {
                    "detected_by": "author_field",
                    "detector_name": "author_field",
                    "wire_service": service,
                    "evidence": f"author='{direct_author[:80]}' matched pattern '{pattern_info['pattern']}'",
                }
    
    # Check existing wire_hints from metadata (if crawler already detected)
    wire_hints = metadata.get("wire_hints")
    if isinstance(wire_hints, dict):
        hint_services = [svc for svc in wire_hints.get("wire_services", []) if svc]
        if hint_services:
            return {
                "detected_by": "existing_wire_hints",
                "detector_name": "existing_wire_hints",
                "wire_service": hint_services[0] if hint_services else "",
                "evidence": f"wire_hints already present: {hint_services}",
            }
    
    # Priority order of NEW detection methods
    detectors = [
        ("canonical_cross_domain", lambda: detect_canonical_cross_domain(metadata, url)),
        ("og_distributor", lambda: detect_og_distributor(metadata)),
        ("jsonld_author", lambda: detect_jsonld_author(metadata, author_patterns)),
        ("jsonld_syndication", lambda: detect_jsonld_syndication(metadata)),
        ("meta_author", lambda: detect_meta_author(metadata, author_patterns)),
        ("datalayer", lambda: detect_datalayer_syndication(metadata)),
    ]
    
    for detector_name, detector_fn in detectors:
        try:
            result = detector_fn()
            if result:
                result["detector_name"] = detector_name
                return result
        except Exception as e:
            pass  # Skip detector on error
    
    return None


def main():
    """Query labeled articles and test new detector, output CSV."""
    db = DatabaseManager()
    
    # CSV output to stdout
    writer = csv.writer(sys.stdout)
    writer.writerow([
        "article_id",
        "url",
        "source",
        "current_status",
        "extracted_at",
        "would_be_wire",
        "detection_method",
        "wire_service",
        "evidence",
    ])
    
    with db.get_session() as session:
        # Load patterns from DB
        print("Loading wire patterns from database...", file=sys.stderr)
        patterns = get_wire_patterns_from_db(session)
        print(f"Loaded patterns: {len(patterns['url'])} URL, {len(patterns['author'])} author, {len(patterns['content'])} content", file=sys.stderr)
        
        # Query labeled articles with their metadata
        print("Querying labeled articles...", file=sys.stderr)
        result = session.execute(text("""
            SELECT 
                a.id,
                a.url,
                a.status,
                a.extracted_at,
                a.metadata,
                a.author,
                cl.source
            FROM articles a
            LEFT JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.status = 'labeled' AND a.wire_check_status = 'complete'
            ORDER BY a.extracted_at DESC
            LIMIT 5000
        """))
        
        articles = result.fetchall()
        print(f"Found {len(articles)} labeled articles to test", file=sys.stderr)
        
        detected_count = 0
        for row in articles:
            article = {
                "id": row.id,
                "url": row.url,
                "status": row.status,
                "extracted_at": row.extracted_at,
                "metadata": row.metadata,
                "author": row.author,
                "source": row.source,
            }
            
            detection = run_new_detection(article, patterns)
            
            if detection:
                detected_count += 1
                writer.writerow([
                    article["id"],
                    article["url"],
                    article["source"],
                    article["status"],
                    article["extracted_at"].isoformat() if article["extracted_at"] else "",
                    "YES",
                    detection.get("detected_by", ""),
                    detection.get("wire_service", ""),
                    detection.get("evidence", ""),
                ])
        
        print(f"\nResults: {detected_count}/{len(articles)} labeled articles would be detected as wire", file=sys.stderr)
        print(f"Detection rate: {100*detected_count/len(articles):.2f}%", file=sys.stderr)


if __name__ == "__main__":
    main()
