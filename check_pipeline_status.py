#!/usr/bin/env python3
"""Check pipeline status"""

from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()

with db.get_session() as session:
    # Get overall status counts
    status_query = text("""
        SELECT 
            status,
            COUNT(*) as count
        FROM articles
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY status
        ORDER BY 
            CASE status
                WHEN 'discovered' THEN 1
                WHEN 'verified' THEN 2
                WHEN 'extracted' THEN 3
                WHEN 'cleaned' THEN 4
                WHEN 'wire' THEN 5
                WHEN 'local' THEN 6
                WHEN 'labeled' THEN 7
                WHEN 'failed' THEN 8
                ELSE 9
            END
    """)

    print('=== PIPELINE STATUS (Last 7 Days) ===')
    print()
    results = session.execute(status_query).fetchall()
    total = sum(r[1] for r in results)

    for status, count in results:
        pct = (count / total * 100) if total > 0 else 0
        print(f'{status:12s}: {count:5d} ({pct:5.1f}%)')

    print()
    print(f'{"TOTAL":12s}: {total:5d}')

    # Get entity extraction status
    entity_query = text("""
        SELECT 
            COUNT(DISTINCT a.id) as articles_with_entities,
            COUNT(e.id) as total_entities,
            COUNT(DISTINCT CASE WHEN e.label = 'SENTINEL' THEN a.id END) as articles_with_sentinel
        FROM articles a
        LEFT JOIN entities e ON a.id = e.article_id
        WHERE a.created_at >= NOW() - INTERVAL '7 days'
            AND a.status IN ('cleaned', 'wire', 'local', 'labeled')
    """)

    print()
    print('=== ENTITY EXTRACTION ===')
    print()
    result = session.execute(entity_query).fetchone()
    print(f'Articles with entities: {result[0]}')
    print(f'Total entities found: {result[1]}')
    print(f'Articles with sentinel (no entities): {result[2]}')

    # Get ML labels status
    label_query = text("""
        SELECT 
            COUNT(DISTINCT article_id) as labeled_articles,
            COUNT(*) as total_labels,
            label_version
        FROM article_labels
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY label_version
        ORDER BY label_version
    """)

    print()
    print('=== ML LABELS ===')
    print()
    label_results = session.execute(label_query).fetchall()
    if label_results:
        for labeled_articles, total_labels, version in label_results:
            print(f'Version {version}: {labeled_articles} articles, {total_labels} labels')
    else:
        print('No labels applied in last 7 days')

    # Get cleaning queue size
    cleaning_query = text("""
        SELECT COUNT(*) 
        FROM articles
        WHERE status = 'extracted'
        AND created_at >= NOW() - INTERVAL '7 days'
    """)
    
    print()
    print('=== QUEUE STATUS ===')
    print()
    cleaning_count = session.execute(cleaning_query).scalar()
    print(f'Articles awaiting cleaning: {cleaning_count}')
