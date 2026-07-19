#!/usr/bin/env python3
"""Analyze source coverage in March 2026."""
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as s:
    # 1. Daily articles in March
    print("=== DAILY EXTRACTION IN MARCH ===")
    r = s.execute(text("""
        SELECT DATE(extracted_at) as dt, COUNT(*) as articles
        FROM articles 
        WHERE extracted_at >= '2026-03-01'
        GROUP BY DATE(extracted_at)
        ORDER BY dt
    """)).fetchall()
    for row in r:
        print(f"  {row[0]}: {row[1]} articles")

    # 2. Total active sources  
    total = s.execute(text("SELECT COUNT(*) FROM sources WHERE status IS NULL OR status = 'active'")).scalar()
    print(f"\nTotal active sources: {total}")

    # 3. Sources with articles in March (via candidate_links.source)
    march_sources = s.execute(text("""
        SELECT COUNT(DISTINCT cl.source)
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.extracted_at >= '2026-03-01'
    """)).scalar()
    print(f"Sources with March articles: {march_sources}")
    print(f"Missing: {total - march_sources}")

    # 4. Which sources are missing?
    print("\n=== SOURCES WITH NO MARCH ARTICLES ===")
    missing = s.execute(text("""
        SELECT s.host, s.canonical_name
        FROM sources s
        WHERE (s.status IS NULL OR s.status = 'active')
        AND s.host NOT IN (
            SELECT DISTINCT cl.source 
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE a.extracted_at >= '2026-03-01'
        )
        ORDER BY s.host
    """)).fetchall()
    for row in missing:
        print(f"  {row[0]}: {row[1]}")
