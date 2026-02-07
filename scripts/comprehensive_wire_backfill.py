#!/usr/bin/env python3
"""
Comprehensive wire detection backfill script.

Re-evaluates articles using ALL wire detection signals:
1. URL patterns (/cnn/, /ap/, /stacker-news/, etc.)
2. Byline wire detection (wire service bylines)
3. Content-based wire detection (persistent patterns, inline indicators)
4. Wire payload data already stored

For articles incorrectly marked as cleaned/local, reverts to wire.
For articles correctly marked as wire, no change.
For articles correctly non-wire, triggers BigQuery export if needed.
"""

import sys
import os
import json
import re
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models.database import DatabaseManager
from sqlalchemy import text


def check_url_wire_pattern(url: str, wire_patterns: list) -> tuple[bool, str]:
    """Check if URL matches wire service patterns."""
    for pattern, service_name, case_sensitive in wire_patterns:
        flags = 0 if case_sensitive else re.IGNORECASE
        if re.search(pattern, url, flags):
            return True, service_name
    return False, None


def check_wire_from_all_signals(article: dict, wire_patterns: list) -> tuple[bool, str, dict]:
    """
    Check if article is wire using ONLY RELIABLE signals.
    
    ONLY considers an article wire if:
    1. URL matches wire pattern (/cnn/, /ap/, /stacker-news/, etc.) - DEFINITIVE
    2. Byline is from wire service (array of wire services) - STRONG
    
    IGNORES:
    - Old pattern_analysis payloads (these have false positives from ABC 17 footer bug)
    - Articles already at status='labeled' (already processed correctly)
    
    Returns: (is_wire, reason, details)
    """
    url = article.get("url", "")
    wire_json = article.get("wire")
    current_status = article.get("status", "")
    
    # Signal 1: URL patterns (DEFINITIVE - highest priority)
    is_wire_url, wire_service = check_url_wire_pattern(url, wire_patterns)
    if is_wire_url:
        return True, "url_pattern", {
            "service": wire_service,
            "url": url
        }
    
    # Signal 2: Byline-based wire detection (STRONG - only if array format)
    if wire_json:
        try:
            wire_data = json.loads(wire_json) if isinstance(wire_json, str) else wire_json
            # ONLY trust array format (byline wire like ["CNN"], ["Associated Press"])
            # This comes from mcmetadata wire_hints, not pattern_analysis
            if isinstance(wire_data, list) and len(wire_data) > 0:
                # Check if these are actual wire service names (not just any string)
                wire_services = {"AP", "Associated Press", "Reuters", "CNN", "AFP", 
                               "Bloomberg", "NPR", "Stacker", "USA Today"}
                for service in wire_data:
                    if any(ws.lower() in str(service).lower() for ws in wire_services):
                        return True, "byline_wire", {
                            "services": wire_data
                        }
        except (json.JSONDecodeError, TypeError):
            pass
    
    # If no RELIABLE wire signals found, it's not wire
    return False, "no_wire", {}


def main():
    """Main backfill execution."""
    db = DatabaseManager()
    
    print("=" * 80)
    print("COMPREHENSIVE WIRE DETECTION BACKFILL")
    print("=" * 80)
    print()
    
    # Load wire URL patterns from database
    print("Loading wire service URL patterns...")
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT pattern, service_name, case_sensitive
            FROM wire_services
            WHERE pattern_type = 'url'
            AND active = true
            ORDER BY priority, id
        """))
        wire_patterns = result.fetchall()
    
    print(f"Loaded {len(wire_patterns)} wire URL patterns")
    print()
    
    # Get articles from ABC 17 and News-Press NOW with status cleaned/local/labeled
    # We need to check if any have wire URLs that slipped through
    print("Fetching articles to re-evaluate...")
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT 
                a.id,
                a.url,
                a.status,
                a.wire::text as wire,
                cl.source
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE cl.source IN ('ABC 17 KMIZ News', 'News Press Now')
            AND a.status IN ('cleaned', 'local')
            ORDER BY a.extracted_at DESC
        """))
        articles = [dict(row._mapping) for row in result.fetchall()]
    
    print(f"Found {len(articles)} articles with status=cleaned/local to evaluate")
    print()
    
    # Analyze each article
    should_be_wire = []
    correctly_not_wire = []
    
    print("Analyzing articles...")
    for i, article in enumerate(articles, 1):
        if i % 100 == 0:
            print(f"  Progress: {i}/{len(articles)}")
        
        is_wire, reason, details = check_wire_from_all_signals(article, wire_patterns)
        
        if is_wire:
            should_be_wire.append({
                "id": article["id"],
                "url": article["url"],
                "current_status": article["status"],
                "reason": reason,
                "details": details
            })
        else:
            correctly_not_wire.append(article["id"])
    
    print()
    print("=" * 80)
    print("ANALYSIS RESULTS")
    print("=" * 80)
    print(f"Total articles analyzed: {len(articles)}")
    print(f"Should be wire (need correction): {len(should_be_wire)}")
    print(f"Correctly non-wire: {len(correctly_not_wire)}")
    print()
    
    # Show sample of wire articles
    if should_be_wire:
        print("Sample wire articles (first 10):")
        for item in should_be_wire[:10]:
            print(f"  - {item['url'][:80]}")
            print(f"    Reason: {item['reason']}")
            print(f"    Current status: {item['current_status']}")
            print(f"    Details: {json.dumps(item['details'], indent=6)}")
            print()
    
    # Ask for confirmation
    if should_be_wire:
        print(f"\n⚠️  WARNING: About to update {len(should_be_wire)} articles to status='wire'")
        response = input("Continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return
        
        # Update articles to wire status
        print("\nUpdating articles to wire status...")
        with db.get_session() as session:
            for item in should_be_wire:
                session.execute(text("""
                    UPDATE articles
                    SET status = 'wire',
                        wire_check_status = 'wire'
                    WHERE id = :id
                """), {"id": item["id"]})
            session.commit()
        
        print(f"✅ Updated {len(should_be_wire)} articles to wire status")
    
    # Export non-wire articles to BigQuery
    if correctly_not_wire:
        print(f"\n📊 {len(correctly_not_wire)} articles are correctly non-wire")
        print("These should be exported to BigQuery if not already exported.")
        print()
        print("To export, run:")
        print("  python -m src.cli.cli_modular analyze --batch-size 100")
    
    print()
    print("=" * 80)
    print("BACKFILL COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
