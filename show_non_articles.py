#!/usr/bin/env python3
"""Show recently identified non-articles from verification process."""

import sqlite3
from datetime import datetime

def main():
    conn = sqlite3.connect('data/mizzou.db')
    cursor = conn.cursor()

    print('VERIFICATION RESULTS SUMMARY:')
    print('=' * 60)

    # Get counts
    cursor.execute('''
        SELECT status, COUNT(*) 
        FROM candidate_links 
        WHERE status IN ("article", "not_article") 
        GROUP BY status
    ''')
    results = cursor.fetchall()
    
    total_verified = 0
    for status, count in results:
        print(f'{status.upper()}: {count:,}')
        total_verified += count
    
    print(f'TOTAL VERIFIED: {total_verified:,}')
    
    # Calculate accuracy
    if results:
        article_count = next((count for status, count in results if status == 'article'), 0)
        accuracy = (article_count / total_verified) * 100 if total_verified > 0 else 0
        print(f'ACCURACY: {accuracy:.1f}% articles detected')

    print('\n' + '=' * 60)
    print('SAMPLE ARTICLES (StorySniffer verified as articles):')
    print('-' * 60)
    
    cursor.execute('''
        SELECT url, source, created_at 
        FROM candidate_links 
        WHERE status = "article" 
        ORDER BY created_at DESC 
        LIMIT 5
    ''')
    
    for i, (url, source, created_at) in enumerate(cursor.fetchall(), 1):
        display_url = url if len(url) <= 70 else url[:67] + '...'
        print(f'{i}. {display_url}')
        print(f'   Source: {source}')
        print(f'   Created: {created_at}')
        print()

    print('=' * 60)
    print('SAMPLE NON-ARTICLES (StorySniffer rejected):')
    print('-' * 60)
    
    cursor.execute('''
        SELECT url, source, created_at 
        FROM candidate_links 
        WHERE status = "not_article" 
        ORDER BY created_at DESC 
        LIMIT 10
    ''')
    
    for i, (url, source, created_at) in enumerate(cursor.fetchall(), 1):
        display_url = url if len(url) <= 70 else url[:67] + '...'
        print(f'{i}. {display_url}')
        print(f'   Source: {source}')
        print(f'   Created: {created_at}')
        print()

    # Show patterns in non-articles
    print('=' * 60)
    print('NON-ARTICLE URL PATTERNS:')
    print('-' * 60)
    
    cursor.execute('''
        SELECT url 
        FROM candidate_links 
        WHERE status = "not_article" 
        ORDER BY created_at DESC 
        LIMIT 20
    ''')
    
    patterns = {}
    for (url,) in cursor.fetchall():
        # Extract common patterns
        if '/newsletter' in url.lower():
            patterns['Newsletter pages'] = patterns.get('Newsletter pages', 0) + 1
        elif '/news/' == url.split('/')[-1] or '/news' == url.split('/')[-1]:
            patterns['News category pages'] = patterns.get('News category pages', 0) + 1
        elif '/category/' in url:
            patterns['Category pages'] = patterns.get('Category pages', 0) + 1
        elif '/calendar/' in url:
            patterns['Calendar pages'] = patterns.get('Calendar pages', 0) + 1
        elif url.endswith('/'):
            patterns['Directory/landing pages'] = patterns.get('Directory/landing pages', 0) + 1
        else:
            patterns['Other'] = patterns.get('Other', 0) + 1
    
    for pattern, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True):
        print(f'{pattern}: {count}')

    conn.close()

if __name__ == '__main__':
    main()