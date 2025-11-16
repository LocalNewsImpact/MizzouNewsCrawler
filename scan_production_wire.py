#!/usr/bin/env python3
"""Scan production articles for wire content using updated detector."""
import csv
import sys
import os
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/backend')

from app.lifecycle import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text

db = DatabaseManager(database_url=os.getenv('DATABASE_URL'))
detector = ContentTypeDetector()

print(f'ContentTypeDetector version: {detector.VERSION}', file=sys.stderr)
print('Scanning...', file=sys.stderr)

with db.get_session() as session:
    result = session.execute(text('''
        SELECT id, url, author, title, content, text
        FROM articles
        WHERE status = 'labeled'
        AND (
            author ILIKE '%afp%'
            OR author ILIKE '%associated press%'
            OR author ILIKE 'ap staff%'
            OR author ILIKE 'by ap%'
            OR author ILIKE 'reuters%'
        )
    '''))
    
    articles = list(result)
    print(f'Found {len(articles)} articles', file=sys.stderr)
    
    # CSV header
    print('id,url,author,title,wire_service')
    
    detected = 0
    for row in articles:
        article_id, url, author, title, content, text_col = row
        metadata = {'byline': author} if author else None
        
        detection = detector.detect(
            url=url or '',
            title=title,
            metadata=metadata,
            content=content or text_col or '',
        )
        
        if detection and detection.status == 'wire':
            detected += 1
            service = 'Unknown'
            if 'author' in detection.evidence:
                ev = str(detection.evidence['author'])
                if 'AFP' in ev: service = 'AFP'
                elif 'Associated Press' in ev: service = 'AP'
                elif 'Reuters' in ev: service = 'Reuters'
            
            # Output CSV row
            print(f'{article_id},{url},{author},{title[:80] if title else ""},{service}')
    
    print(f'Detected {detected}/{len(articles)} as wire', file=sys.stderr)
