#!/usr/bin/env python
"""Check for candidate_links marked as extracted but not in articles table."""

from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()

# Count candidate_links marked as extracted but not in articles table
query = """
SELECT
    cl.status,
    COUNT(*) as count
FROM candidate_links cl
LEFT JOIN articles a ON a.url = cl.url
WHERE cl.status IN ('extracted', 'labeled', 'wire', 'obituary')
  AND cl.fetched_at >= '2025-10-22 19:54:00'
  AND a.id IS NULL
GROUP BY cl.status
ORDER BY count DESC
"""

result = db.session.execute(text(query))
orphaned = list(result)

print('Candidate links marked as extracted but NOT in articles table (since Oct 22):')
for row in orphaned:
    print(f'  {row[0]}: {row[1]}')

total_orphaned = sum(row[1] for row in orphaned)
print(f'\nTotal orphaned: {total_orphaned}')

# Show sample URLs
query2 = """
SELECT cl.url, cl.status, cl.fetched_at
FROM candidate_links cl
LEFT JOIN articles a ON a.url = cl.url
WHERE cl.status IN ('extracted', 'labeled', 'wire', 'obituary')
  AND cl.fetched_at >= '2025-10-22 19:54:00'
  AND a.id IS NULL
ORDER BY cl.fetched_at DESC
LIMIT 10
"""

result = db.session.execute(text(query2))
samples = list(result)

print('\nSample orphaned URLs:')
for row in samples:
    print(f'  {row[2]} | {row[1]} | {row[0][:70]}')
