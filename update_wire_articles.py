#!/usr/bin/env python3
"""
Update articles in production database to mark them as wire content.
Reads article IDs from CSV and updates their status to 'wire'.
"""

import sys
import os
import re

# Add project root to path to import database utilities
sys.path.insert(0, '/app')

from src.models.database import get_session_local

# UUID validation pattern
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def is_valid_uuid(value):
    """Check if value is a valid UUID."""
    return UUID_PATTERN.match(str(value)) is not None


def extract_article_ids(csv_path):
    """Extract valid article UUIDs from CSV file."""
    article_ids = []
    
    print(f"Reading CSV from: {csv_path}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
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
                if is_valid_uuid(potential_id):
                    article_ids.append(potential_id)
    
    print(f"Extracted {len(article_ids)} valid article IDs")
    return article_ids


def update_articles_to_wire(article_ids, batch_size=500):
    """Update articles in production database to wire status."""
    
    print("Connecting to database...")
    SessionLocal = get_session_local()
    session = SessionLocal()
    
    total_updated = 0
    
    try:
        # Process in batches to avoid query size limits
        for i in range(0, len(article_ids), batch_size):
            batch = article_ids[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(article_ids) + batch_size - 1) // batch_size
            
            batch_info = (
                f"Processing batch {batch_num}/{total_batches} "
                f"({len(batch)} articles)..."
            )
            print(batch_info)
            
            # Build parameterized query
            placeholders = ','.join([f"'{aid}'" for aid in batch])
            query = f"""
                UPDATE articles
                SET status = 'wire'
                WHERE id IN ({placeholders})
                AND status != 'wire'
            """
            
            result = session.execute(query)
            session.commit()
            updated = result.rowcount
            total_updated += updated
            print(f"  Updated {updated} articles in batch {batch_num}")
        
        print("\n=== COMPLETE ===")
        print(f"Total articles updated to WIRE status: {total_updated}")
        print(f"Total IDs processed: {len(article_ids)}")
        
        if total_updated < len(article_ids):
            already_wire = len(article_ids) - total_updated
            print(f"Note: {already_wire} articles were already marked as wire")
    
    finally:
        session.close()


if __name__ == '__main__':
    csv_path = '/tmp/wire_articles.csv'
    
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV file not found at {csv_path}")
        sys.exit(1)
    
    article_ids = extract_article_ids(csv_path)
    
    if not article_ids:
        print("ERROR: No valid article IDs found in CSV")
        sys.exit(1)
    
    print(f"\nReady to update {len(article_ids)} articles to WIRE status")
    print("This will modify the production database.")
    print("\nProceeding with update...")
    
    update_articles_to_wire(article_ids)
