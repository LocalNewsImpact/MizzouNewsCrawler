#!/usr/bin/env python3
"""Query production database for broadcaster sources."""

from sqlalchemy import text
from src.models.database import DatabaseManager

db = DatabaseManager()
with db.get_session() as session:
    # Get Missouri sources that look like broadcasters
    results = session.execute(text("""
        SELECT 
            id,
            host,
            canonical_name,
            city,
            county
        FROM sources 
        WHERE status = 'active'
        AND (
            canonical_name ~* '\\b[KW][A-Z]{3,4}\\b'
            OR host ~* '\\b[KW][A-Z]{3,4}\\b'
        )
        ORDER BY canonical_name
    """)).fetchall()
    
    if not results:
        print("No broadcaster sources found")
    else:
        print(f"Found {len(results)} potential broadcasters:")
        print("-" * 80)
        for row in results:
            print(f"ID: {row[0]}")
            print(f"  Host: {row[1]}")
            print(f"  Name: {row[2]}")
            print(f"  City: {row[3]}")
            print(f"  County: {row[4]}")
            print()
