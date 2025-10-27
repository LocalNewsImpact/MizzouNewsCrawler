#!/usr/bin/env python
"""Check if recent articles were written to database."""

from src.models.database import DatabaseManager
from sqlalchemy import text
from datetime import datetime, timedelta

db = DatabaseManager()

# Check articles created in last 5 minutes
cutoff = datetime.utcnow() - timedelta(minutes=5)
result = db.session.execute(
    text('SELECT COUNT(*) FROM articles WHERE created_at >= :cutoff'),
    {'cutoff': cutoff}
)
count_recent = result.scalar()

# Get total count
result = db.session.execute(text('SELECT COUNT(*) FROM articles'))
count_total = result.scalar()

print(f'Articles created in last 5 minutes: {count_recent}')
print(f'Total articles in database: {count_total}')

if count_recent > 0:
    # Show the newest articles
    result = db.session.execute(
        text('SELECT url, status, created_at FROM articles ORDER BY created_at DESC LIMIT 10')
    )
    print('\n✅ NEWEST ARTICLES (database writes ARE working!):')
    for row in result:
        print(f'  {row[2]} | {row[1]} | {row[0][:65]}')
    print(f'\n🎉 FIX CONFIRMED: {count_recent} new articles written successfully!')
else:
    print('\n❌ NO NEW ARTICLES - database writes still failing!')
