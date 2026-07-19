#!/usr/bin/env python3
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as s:
    result = s.execute(text("""
        WITH missing AS (
            SELECT src.id, src.host, src.canonical_name
            FROM sources src
            LEFT JOIN candidate_links cl ON cl.source_id = src.id
            LEFT JOIN articles a ON a.candidate_link_id = cl.id 
                AND a.extracted_at >= '2026-03-01'
            WHERE src.status IS NULL OR src.status = 'active'
            GROUP BY src.id
            HAVING COUNT(a.id) = 0
        )
        SELECT 
            m.canonical_name, 
            m.host,
            MAX(cl.discovered_at) as last_discovery,
            COUNT(cl.id) as total_links
        FROM missing m
        LEFT JOIN candidate_links cl ON cl.source_id = m.id
        GROUP BY m.id, m.canonical_name, m.host
        ORDER BY last_discovery DESC NULLS LAST
    """)).fetchall()
    
    print("48 SOURCES WITH NO MARCH ARTICLES - LAST DISCOVERY DATE:\n")
    for row in result:
        name = (row[0] or row[1])[:40]
        last = str(row[2])[:10] if row[2] else "NEVER"
        print(f"{last:12} | {row[3]:>5} links | {name}")
