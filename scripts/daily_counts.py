#!/usr/bin/env python3
"""
Query daily counts of discovered URLs and extracted articles for December and January.
"""

import sys
sys.path.insert(0, '/app')

from sqlalchemy import text
from src.models.database import DatabaseManager

db = DatabaseManager()
with db.get_session() as session:
    print('=== DISCOVERED URLs per day (December & January) ===')
    result = session.execute(text('''
        SELECT DATE(discovered_at) as date, COUNT(*) as discovered_count
        FROM candidate_links
        WHERE discovered_at >= '2025-12-01' AND discovered_at < '2026-02-01'
        GROUP BY DATE(discovered_at)
        ORDER BY date
    ''')).fetchall()

    for row in result:
        print(f'{row[0]}: {row[1]} discovered URLs')

    print()
    print('=== EXTRACTED ARTICLES per day (December & January) ===')
    result = session.execute(text('''
        SELECT DATE(extracted_at) as date, COUNT(*) as articles_count
        FROM articles
        WHERE extracted_at >= '2025-12-01' AND extracted_at < '2026-02-01'
        GROUP BY DATE(extracted_at)
        ORDER BY date
    ''')).fetchall()

    for row in result:
        print(f'{row[0]}: {row[1]} extracted articles')