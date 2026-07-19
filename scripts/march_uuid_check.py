#!/usr/bin/env python3
"""Check March article coverage using proper UUID joins."""
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as s:
    print("=== MARCH ARTICLES BY SOURCE (UUID JOIN) ===\n")
    
    result = s.execute(text("""
        SELECT 
            src.host,
            src.canonical_name,
            COUNT(a.id) as article_count
        FROM sources src
        LEFT JOIN candidate_links cl ON cl.source_id = src.id
        LEFT JOIN articles a ON a.candidate_link_id = cl.id 
            AND a.extracted_at >= '2026-03-01' 
            AND a.extracted_at < '2026-03-09'
        WHERE src.status IS NULL OR src.status = 'active'
        GROUP BY src.id, src.host, src.canonical_name
        ORDER BY article_count DESC
    """)).fetchall()
    
    total = len(result)
    with_articles = sum(1 for r in result if r[2] > 0)
    without_articles = sum(1 for r in result if r[2] == 0)
    
    print(f"Total active sources: {total}")
    print(f"Sources with March articles: {with_articles}")
    print(f"Sources without March articles: {without_articles}")
    
    print("\n=== TOP 20 SOURCES ===")
    for row in result[:20]:
        print(f"{row[2]:>5} articles: {row[1] or row[0]}")
    
    if without_articles > 0:
        print(f"\n=== SOURCES WITH 0 MARCH ARTICLES ({without_articles}) ===")
        for row in result:
            if row[2] == 0:
                print(f"  {row[1] or row[0]} ({row[0]})")
