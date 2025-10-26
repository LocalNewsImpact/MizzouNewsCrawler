#!/usr/bin/env python3
"""Check Penn-State-Lehigh dataset in cloud database."""
import os
os.environ["DATABASE_ENGINE"] = "postgresql+psycopg2"

from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = db.session

# Get dataset info
result = session.execute(text("""
    SELECT id, slug, name FROM source_lists 
    WHERE slug = 'Penn-State-Lehigh'
"""))
dataset = result.fetchone()

if dataset:
    print(f"Dataset: {dataset.slug} - {dataset.name}")
    print(f"ID: {dataset.id}")
    
    # Check for unextracted articles
    result2 = session.execute(text("""
        SELECT COUNT(*) 
        FROM candidate_links cl
        WHERE cl.dataset_id = :dataset_id
        AND cl.status = 'article'
        AND NOT EXISTS (
            SELECT 1 FROM articles a 
            WHERE a.candidate_link_id = cl.id
        )
    """), {"dataset_id": dataset.id})
    count = result2.scalar()
    print(f"Unextracted articles: {count}")
    
    if count > 0:
        result3 = session.execute(text("""
            SELECT id, url, source_name 
            FROM candidate_links cl
            WHERE dataset_id = :dataset_id
            AND status = 'article'
            AND NOT EXISTS (
                SELECT 1 FROM articles a 
                WHERE a.candidate_link_id = cl.id
            )
            LIMIT 5
        """), {"dataset_id": dataset.id})
        print("\nSample unextracted URLs:")
        for row in result3:
            print(f"  {row.url}")
else:
    print("Penn-State-Lehigh dataset not found")

session.close()
