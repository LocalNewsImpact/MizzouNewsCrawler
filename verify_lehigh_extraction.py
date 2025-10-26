#!/usr/bin/env python3
"""Verify Penn-State-Lehigh extraction in cloud database."""
import os
os.environ["DATABASE_ENGINE"] = "postgresql+psycopg2"

from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = db.session

# Get dataset
result = session.execute(text("""
    SELECT id, slug, name FROM source_lists 
    WHERE slug = 'Penn-State-Lehigh'
"""))
dataset = result.fetchone()

if not dataset:
    print("Penn-State-Lehigh dataset not found in cloud database")
    session.close()
    exit(1)

print(f"Dataset: {dataset.slug} - {dataset.name}")
print(f"ID: {dataset.id}")

# Count total articles
result2 = session.execute(text("""
    SELECT COUNT(*) FROM candidate_links 
    WHERE dataset_id = :did AND status = 'article'
"""), {"did": dataset.id})
total = result2.scalar()
print(f"\nTotal articles marked as 'article': {total}")

# Count extracted articles
result3 = session.execute(text("""
    SELECT COUNT(*) FROM articles a 
    JOIN candidate_links cl ON a.candidate_link_id = cl.id 
    WHERE cl.dataset_id = :did
"""), {"did": dataset.id})
extracted = result3.scalar()
print(f"Extracted articles: {extracted}")
print(f"Unextracted: {total - extracted}")

# Show recent extractions
result4 = session.execute(text("""
    SELECT a.title, a.url, a.created_at 
    FROM articles a 
    JOIN candidate_links cl ON a.candidate_link_id = cl.id 
    WHERE cl.dataset_id = :did 
    ORDER BY a.created_at DESC 
    LIMIT 5
"""), {"did": dataset.id})

print("\n=== Recent Extractions ===")
rows = result4.fetchall()
if rows:
    for row in rows:
        print(f"\n  Created: {row.created_at}")
        print(f"  Title: {row.title}")
        print(f"  URL: {row.url[:80]}...")
else:
    print("  None")

session.close()
