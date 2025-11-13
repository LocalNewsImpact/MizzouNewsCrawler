"""Simple scan script to run in production pod."""
import csv
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/backend')

from app.lifecycle import DatabaseManager
from sqlalchemy import text, or_
import os

# Import the UPDATED content_type_detector code
import re

class ContentTypeDetector:
    """Updated detector with author field checking."""
    VERSION = "2025-11-12a"
    
    def detect(self, url, title, metadata, content):
        """Detect wire based on author field."""
        author = (metadata or {}).get("byline", "") if metadata else ""
        
        if author:
            author_lower = author.lower().strip()
            # Check for wire service author patterns
            wire_patterns = [
                (r"^afp\s+afp$", "AFP"),
                (r"^(by\s+)?afp(\s+staff)?$", "AFP"),
                (r"\bafp$", "AFP"),
                (r"^(by\s+)?ap(\s+staff)?$", "Associated Press"),
                (r"^(by\s+)?reuters(\s+staff)?$", "Reuters"),
            ]
            for pattern, service in wire_patterns:
                if re.search(pattern, author_lower, re.IGNORECASE):
                    return type('Result', (), {
                        'status': 'wire',
                        'confidence': 'high',
                        'reason': f'Author field: {author}',
                        'evidence': {'author': [f'{service} (author field)']},
                    })()
        return None

db = DatabaseManager(database_url=os.getenv('DATABASE_URL'))
detector = ContentTypeDetector()

print(f'Detector version: {detector.VERSION}')
print('=' * 80)

with db.get_session() as session:
    result = session.execute(text('''
        SELECT id, url, author, title
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
    print(f'Found {len(articles)} articles with wire author patterns')
    
    results = []
    for i, row in enumerate(articles, 1):
        if i % 50 == 0:
            print(f'Progress: {i}/{len(articles)}')
        
        article_id, url, author, title = row
        metadata = {'byline': author} if author else None
        
        detection = detector.detect(
            url=url or '',
            title=title,
            metadata=metadata,
            content='',
        )
        
        if detection and detection.status == 'wire':
            service = 'Unknown'
            if 'author' in detection.evidence:
                ev = str(detection.evidence['author'])
                if 'AFP' in ev: service = 'AFP'
                elif 'Associated Press' in ev: service = 'AP'
                elif 'Reuters' in ev: service = 'Reuters'
            
            results.append({
                'id': str(article_id),
                'url': url or '',
                'author': author or '',
                'title': (title[:80] if title else '')[:80],
                'wire_service': service,
            })
    
    print(f'\nDetected {len(results)}/{len(articles)} as wire')
    
    with open('/tmp/wire_articles_new.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'url', 'author', 'title', 'wire_service'])
        writer.writeheader()
        writer.writerows(results)
    
    print('CSV written to /tmp/wire_articles_new.csv')
    
    # Summary
    counts = {}
    for row in results:
        service = row['wire_service']
        counts[service] = counts.get(service, 0) + 1
    
    print('\nBy wire service:')
    for service, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        print(f'  {service}: {count}')
