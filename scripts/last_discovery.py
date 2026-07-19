#!/usr/bin/env python3
"""Check last discovery date for missing sources."""
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as s:
    print("=== LAST DISCOVERY DATE FOR MISSING SOURCES ===\n")
    
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
    
    results = []
    for src_id, host, name in missing_sources:
        last_discovery = s.execute(text("""
            SELECT MAX(discovered_at) FROM candidate_links WHERE source_id = :sid
        """), {"sid": src_id}).scalar()
        
        paused_count = s.execute(text("""
            SELECT COUNT(*) FROM candidate_links WHERE source_id = :sid AND status = 'paused'
        """), {"sid": src_id}).scalar()
        
        total = s.execute(text("""
            SELECT COUNT(*) FROM candidate_links WHERE source_id = :sid
        """), {"sid": src_id}).scalar()
        
        display = (name if name else host)[:40]
        results.append((display, last_discovery, total, paused_count))
    
    # Sort by last discovery date (most recent first)
    results.sort(key=lambda x: x[1] if x[1] else "1970-01-01", reverse=True)
    
    print("SOURCE                                    | LAST DISCOVERY      | TOTAL | PAUSED")
    print("-" * 90)
    for display, last_disc, total, paused in results:
        last_str = str(last_disc)[:19] if last_disc else "NEVER"
        print(f"{display:40} | {last_str:19} | {total:>5} | {paused:>5}")
