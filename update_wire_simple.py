#!/usr/bin/env python3
"""
Update articles in production database to mark them as wire content.
"""

import sys
import os
import re

sys.path.insert(0, '/app')

from src.models.database import DatabaseManager
from sqlalchemy import text

# UUID validation pattern
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def extract_article_ids(csv_path):
    """Extract valid article UUIDs from CSV file."""
    article_ids = []
    
    print(f"Reading CSV from: {csv_path}")
    
    with open(csv_path, encoding='utf-8') as f:
        for line in f:
            # Skip progress messages and summary lines
            skip_prefixes = (
                'Processing batch', 'Found ', 'Counting', '===',
                'Total articles', 'Articles to mark'
            )
            if line.startswith(skip_prefixes):
                continue
            
            # Skip header
            if line.startswith('id,url,title'):
                continue
            
            # Extract first field (article ID)
            parts = line.split(',', 1)
            if len(parts) > 0:
                potential_id = parts[0].strip()
                if UUID_PATTERN.match(potential_id):
                    article_ids.append(potential_id)
    
    print(f"Extracted {len(article_ids)} valid article IDs")
    return article_ids


def update_articles(article_ids, batch_size=500):
    """Update articles to wire status."""
    
    print("Initializing database connection...")
    db = DatabaseManager()
    
    total_updated = 0
    
    # Process in batches
    for i in range(0, len(article_ids), batch_size):
        batch = article_ids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(article_ids) + batch_size - 1) // batch_size
        
        print(f"Batch {batch_num}/{total_batches} ({len(batch)} articles)...")
        
        # Build SQL with direct UUID values
        placeholders = ','.join([f"'{aid}'" for aid in batch])
        sql = text(f"""
            UPDATE articles
            SET status = 'wire'
            WHERE id IN ({placeholders})
            AND status != 'wire'
        """)
        
        with db.get_session() as session:
            result = session.execute(sql)
            session.commit()
            updated = result.rowcount
            total_updated += updated
            print(f"  Updated {updated} articles")
    
    print("\n=== COMPLETE ===")
    print(f"Total updated to WIRE: {total_updated}")
    print(f"Total IDs processed: {len(article_ids)}")
    
    if total_updated < len(article_ids):
        print(f"Note: {len(article_ids) - total_updated} already wire")


if __name__ == '__main__':
    csv_path = '/tmp/wire_articles.csv'
    
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found at {csv_path}")
        sys.exit(1)
    
    article_ids = extract_article_ids(csv_path)
    
    if not article_ids:
        print("ERROR: No valid article IDs found")
        sys.exit(1)
    
    print(f"\nUpdating {len(article_ids)} articles to WIRE status...")
    update_articles(article_ids)
