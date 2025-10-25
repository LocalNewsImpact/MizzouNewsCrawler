#!/usr/bin/env python
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()

# Run the EXACT query extraction uses
query = text("""
    SELECT COUNT(*) FROM candidate_links cl
    WHERE cl.status = 'article'
    AND (cl.dataset_id IS NULL OR cl.dataset_id IN 
        (SELECT id FROM datasets WHERE cron_enabled IS TRUE))
    AND cl.id NOT IN 
        (SELECT candidate_link_id FROM articles 
         WHERE candidate_link_id IS NOT NULL)
""")

count = db.session.execute(query).scalar()
print(f'Articles ready for extraction: {count:,}')

if count > 0:
    query2 = text("""
        SELECT id, url, dataset_id FROM candidate_links cl
        WHERE cl.status = 'article'
        AND (cl.dataset_id IS NULL OR cl.dataset_id IN 
            (SELECT id FROM datasets WHERE cron_enabled IS TRUE))
        AND cl.id NOT IN 
            (SELECT candidate_link_id FROM articles 
             WHERE candidate_link_id IS NOT NULL)
        LIMIT 10
    """)
    
    result = db.session.execute(query2)
    print('\nSample URLs ready to extract:')
    for row in result:
        dataset = row[2] if row[2] else 'NULL'
        print(f'  {row[0]} | dataset: {dataset} | {row[1][:50]}')
else:
    print('\n❌ NO ARTICLES FOUND - all have already been extracted!')
