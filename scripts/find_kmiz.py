#!/usr/bin/env python3
"""Find ABC 17 KMIZ source."""

from sqlalchemy import text
from src.models.database import DatabaseManager

db = DatabaseManager()
with db.get_session() as session:
    results = session.execute(text("""
        SELECT id, host, canonical_name, city, county
        FROM sources 
        WHERE host ILIKE '%abc17%' OR host ILIKE '%kmiz%'
        OR canonical_name ILIKE '%abc 17%'
        ORDER BY canonical_name
        LIMIT 10
    """)).fetchall()
    
    if not results:
        print("No ABC 17 / KMIZ sources found")
    else:
        print(f"Found {len(results)} sources:")
        print("-" * 80)
        for row in results:
            print(f"ID: {row[0]}")
            print(f"  Host: {row[1]}")
            print(f"  Name: {row[2]}")
            print(f"  City: {row[3]}")
            print(f"  County: {row[4]}")
            print()
