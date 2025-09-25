#!/usr/bin/env python3
"""
Script to find URLs that failed with missing fields for testing purposes.
"""

import sqlite3
import sys
import os
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def get_db_path():
    """Get the database path."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base_dir, 'data', 'mizzou.db')

def find_urls_with_missing_fields(limit=10, days_back=30):
    """
    Find URLs that have missing fields from recent extractions.
    
    Args:
        limit: Maximum number of URLs to return
        days_back: How many days back to look for extractions
    """
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"Database not found at: {db_path}")
        return []
    
    # Calculate date threshold
    cutoff_date = datetime.now() - timedelta(days=days_back)
    cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # This allows dict-like access
    
    try:
        cursor = conn.cursor()
        
        # Query for articles with missing fields from recent extractions
        query = """
        SELECT DISTINCT url, title, author, content, publish_date,
               created_at, extracted_at
        FROM articles
        WHERE extracted_at >= ?
        AND (
            title IS NULL OR title = '' OR
            author IS NULL OR author = '' OR
            content IS NULL OR LENGTH(content) < 100 OR
            publish_date IS NULL OR publish_date = ''
        )
        ORDER BY extracted_at DESC
        LIMIT ?
        """
        
        cursor.execute(query, (cutoff_str, limit))
        results = cursor.fetchall()
        
        print(f"\n{'='*80}")
        print(f"FOUND {len(results)} URLs WITH MISSING FIELDS")
        print(f"(Looking back {days_back} days from {cutoff_date.strftime('%Y-%m-%d')})")
        print(f"{'='*80}")
        
        urls_for_testing = []
        
        for i, row in enumerate(results, 1):
            url = row['url']
            urls_for_testing.append(url)
            
            print(f"\n{i}. URL: {url}")
            print(f"   Last extracted: {row['extracted_at']}")
            
            # Check which fields are missing
            missing = []
            if not row['title']:
                missing.append('title')
            if not row['author']:
                missing.append('author')
            if not row['content'] or len(row['content']) < 100:
                missing.append('content')
            if not row['publish_date']:
                missing.append('publish_date')
                
            print(f"   Missing fields: {', '.join(missing)}")
            
            # Show what we do have
            if row['title']:
                print(f"   Title: {row['title'][:60]}...")
            if row['content'] and len(row['content']) >= 50:
                print(f"   Content: {len(row['content'])} chars")
                
        print(f"\n{'='*80}")
        print("URLS FOR TESTING:")
        for url in urls_for_testing:
            print(f"  \"{url}\",")
        print(f"{'='*80}")
        
        return urls_for_testing
        
    except Exception as e:
        print(f"Error querying database: {e}")
        return []
    finally:
        conn.close()

def find_specific_patterns():
    """Find URLs with specific missing field patterns."""
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"Database not found at: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    patterns = [
        ("Missing only author", "title IS NOT NULL AND title != '' AND content IS NOT NULL AND LENGTH(content) >= 100 AND publish_date IS NOT NULL AND publish_date != '' AND (author IS NULL OR author = '')"),
        ("Missing only title", "author IS NOT NULL AND author != '' AND content IS NOT NULL AND LENGTH(content) >= 100 AND publish_date IS NOT NULL AND publish_date != '' AND (title IS NULL OR title = '')"),
        ("Missing only date", "title IS NOT NULL AND title != '' AND author IS NOT NULL AND author != '' AND content IS NOT NULL AND LENGTH(content) >= 100 AND (publish_date IS NULL OR publish_date = '')"),
        ("Missing only content", "title IS NOT NULL AND title != '' AND author IS NOT NULL AND author != '' AND publish_date IS NOT NULL AND publish_date != '' AND (content IS NULL OR LENGTH(content) < 100)"),
        ("Missing multiple fields", "(title IS NULL OR title = '') AND (author IS NULL OR author = '') AND (content IS NULL OR LENGTH(content) < 100)")
    ]
    
    try:
        print(f"\n{'='*80}")
        print("SPECIFIC MISSING FIELD PATTERNS")
        print(f"{'='*80}")
        
        for pattern_name, condition in patterns:
            cursor = conn.cursor()
            query = f"""
            SELECT url, title, author, content, publish_date, extracted_at
            FROM articles
            WHERE {condition}
            AND extracted_at IS NOT NULL
            ORDER BY extracted_at DESC
            LIMIT 5
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            print(f"\n{pattern_name}: {len(results)} found")
            for row in results:
                print(f"  {row['url']}")
                
    except Exception as e:
        print(f"Error finding patterns: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Find URLs with missing fields for testing')
    parser.add_argument('--limit', type=int, default=10, help='Number of URLs to return (default: 10)')
    parser.add_argument('--days', type=int, default=30, help='Days back to search (default: 30)')
    parser.add_argument('--patterns', action='store_true', help='Show specific missing field patterns')
    
    args = parser.parse_args()
    
    if args.patterns:
        find_specific_patterns()
    else:
        urls = find_urls_with_missing_fields(args.limit, args.days)
        
        if urls:
            print(f"\nFound {len(urls)} URLs that can be used for real-world testing.")
            print("You can copy these URLs into your test methods to replace the mock data.")
        else:
            print("\nNo URLs with missing fields found in the specified time range.")
            print("Try increasing --days or check if extractions have been running recently.")