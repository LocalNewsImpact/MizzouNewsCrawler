#!/usr/bin/env python3
"""Export Penn-State-Lehigh article sample to CSV."""
import os
import csv
from datetime import datetime

os.environ['DATABASE_ENGINE'] = 'postgresql+psycopg2'

from src.models.database import DatabaseManager
from sqlalchemy import text, inspect

db = DatabaseManager()
session = db.session

# Get dataset ID
result = session.execute(text("""
    SELECT id FROM datasets WHERE slug = 'Penn-State-Lehigh'
"""))
dataset = result.fetchone()

if not dataset:
    print("Penn-State-Lehigh dataset not found")
    session.close()
    exit(1)

dataset_id = dataset.id

# Get article schema
inspector = inspect(db.engine)
columns = inspector.get_columns('articles')

print("=== Articles Table Schema ===")
print(f"Total columns: {len(columns)}\n")
for col in columns:
    nullable = "NULL" if col['nullable'] else "NOT NULL"
    col_type = str(col['type'])
    default = f" DEFAULT {col['default']}" if col['default'] else ""
    print(f"  {col['name']:<25} {col_type:<30} {nullable}{default}")

# Get a sample article
result = session.execute(text("""
    SELECT 
        a.*,
        cl.url as candidate_url,
        cl.source_name,
        cl.source_city,
        cl.source_county,
        cl.source_state
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE cl.dataset_id = :did
    ORDER BY a.created_at DESC
    LIMIT 1
"""), {"did": dataset_id})

article = result.fetchone()

if not article:
    print("\nNo articles found for Penn-State-Lehigh")
    session.close()
    exit(1)

print("\n=== Sample Article ===")
print(f"Title: {article.title}")
print(f"URL: {article.url}")
print(f"Author: {article.author}")
print(f"Publish Date: {article.publish_date}")
print(f"Created: {article.created_at}")
print(f"Source: {article.source_name} ({article.source_city}, {article.source_county}, {article.source_state})")

# Export to CSV
output_file = 'penn_state_lehigh_sample.csv'

# Get all column names from the article
column_names = article._mapping.keys()

with open(output_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=column_names)
    writer.writeheader()
    
    # Convert row to dict
    row_dict = {}
    for col in column_names:
        value = getattr(article, col, None)
        # Convert datetime objects to strings
        if isinstance(value, datetime):
            value = value.isoformat()
        # Convert None to empty string
        if value is None:
            value = ''
        # Truncate very long text fields for readability
        if col in ('content', 'text') and value and len(str(value)) > 1000:
            value = str(value)[:1000] + f'... [truncated, total length: {len(str(value))}]'
        row_dict[col] = value
    
    writer.writerow(row_dict)

print(f"\n✅ Exported to: {output_file}")
print(f"Columns: {len(column_names)}")

session.close()
