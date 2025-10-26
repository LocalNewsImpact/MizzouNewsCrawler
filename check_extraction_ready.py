#!/usr/bin/env python
"""Check candidate_links ready for extraction."""

from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()

# Check count with status='article'
result = db.session.execute(text("SELECT COUNT(*) FROM candidate_links WHERE status = 'article'"))
count = result.scalar()
print(f'Candidate links with status=article: {count}')

if count > 0:
    # Get samples
    result = db.session.execute(text(
        "SELECT id, url, status FROM candidate_links WHERE status = 'article' LIMIT 5"
    ))
    print('\nSample candidate_links with status=article:')
    for row in result:
        print(f'  ID: {row[0]}')
        print(f'  URL: {row[1][:80]}')
        print(f'  Status: {row[2]}')
        print()
else:
    print('NO candidate_links with status=article found!')
    
    # Show what statuses DO exist
    result = db.session.execute(text(
        "SELECT status, COUNT(*) FROM candidate_links GROUP BY status ORDER BY COUNT(*) DESC LIMIT 10"
    ))
    print('\nAvailable statuses:')
    for row in result:
        print(f'  {row[0]}: {row[1]}')
