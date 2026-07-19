#!/usr/bin/env python3
"""Diagnose why 48 sources have no March articles."""
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as s:
    print("=== DIAGNOSING 48 MISSING SOURCES ===\n")
    
    # Find sources with 0 March articles
    missing_sources = s.execute(text("""
        SELECT 
            src.id,
            src.host,
            src.canonical_name
        FROM sources src
        LEFT JOIN candidate_links cl ON cl.source_id = src.id
        LEFT JOIN articles a ON a.candidate_link_id = cl.id 
            AND a.extracted_at >= '2026-03-01' 
            AND a.extracted_at < '2026-03-09'
        WHERE (src.status IS NULL OR src.status = 'active')
        GROUP BY src.id, src.host, src.canonical_name
        HAVING COUNT(a.id) = 0
    """)).fetchall()
    
    print(f"Total missing sources: {len(missing_sources)}\n")
    
    # For each missing source, check candidate_links status
    print("SOURCE | MARCH CANDIDATE_LINKS | ALL CANDIDATE_LINKS | STATUS BREAKDOWN")
    print("-" * 100)
    
    for src_id, host, name in missing_sources[:25]:
        # Count March candidate links
        march_cl = s.execute(text("""
            SELECT COUNT(*) FROM candidate_links 
            WHERE source_id = :sid 
            AND discovered_at >= '2026-03-01'
        """), {"sid": src_id}).scalar()
        
        # Total candidate links
        total_cl = s.execute(text("""
            SELECT COUNT(*) FROM candidate_links WHERE source_id = :sid
        """), {"sid": src_id}).scalar()
        
        # Status breakdown
        statuses = s.execute(text("""
            SELECT status, COUNT(*) FROM candidate_links 
            WHERE source_id = :sid 
            GROUP BY status
        """), {"sid": src_id}).fetchall()
        status_str = ", ".join(f"{s[0]}:{s[1]}" for s in statuses) if statuses else "none"
        
        display = name if name else host
        print(f"{display[:35]:35} | {march_cl:>5} March | {total_cl:>5} total | {status_str}")
    
    print("\n=== ISSUE CATEGORIES ===")
    
    no_links = 0
    has_links_no_articles = 0
    
    for src_id, host, name in missing_sources:
        total_cl = s.execute(text("""
            SELECT COUNT(*) FROM candidate_links WHERE source_id = :sid
        """), {"sid": src_id}).scalar()
        
        if total_cl == 0:
            no_links += 1
        else:
            has_links_no_articles += 1
    
    print(f"No candidate_links at all: {no_links} (discovery never ran)")
    print(f"Has candidate_links but no articles: {has_links_no_articles} (extraction failed)")
