#!/usr/bin/env python3
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    # Get last 50 discovered URLs from Joplin Globe
    results = session.execute(text("""
        SELECT 
            cl.url,
            cl.status,
            cl.discovered_at,
            a.status as article_status
        FROM candidate_links cl
        LEFT JOIN articles a ON a.candidate_link_id = cl.id
        WHERE cl.source_id = 'f6e3e29b-d575-414a-8a36-0c3d042b6593'
        ORDER BY cl.discovered_at DESC
        LIMIT 50
    """)).fetchall()
    
    print("Last 50 discovered URLs from Joplin Globe:\n")
    for i, row in enumerate(results, 1):
        article_status = f" → {row[3]}" if row[3] else ""
        print(f"{i}. [{row[2]}] {row[1]}{article_status}")
        print(f"   {row[0]}\n")
