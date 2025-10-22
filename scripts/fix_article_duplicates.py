#!/usr/bin/env python3
"""
Fix duplicate articles and add unique constraint on URL.
This must be run with extraction stopped to prevent new duplicates.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from sqlalchemy import text


def clean_duplicates():
    """Delete duplicate articles, keeping most recent."""
    db = DatabaseManager()
    conn = db.engine.connect().execution_options(isolation_level='AUTOCOMMIT')

    print("Step 1: Deleting child records for duplicates...")
    
    # Delete article_labels
    result = conn.execute(text('''
        DELETE FROM article_labels
        WHERE article_id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                FROM articles
            ) t WHERE t.rn > 1
        )
    '''))
    print(f"  Deleted {result.rowcount} article_labels")
    
    # Delete article_entities
    result = conn.execute(text('''
        DELETE FROM article_entities  
        WHERE article_id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                FROM articles
            ) t WHERE t.rn > 1
        )
    '''))
    print(f"  Deleted {result.rowcount} article_entities")
    
    # Delete ml_results
    result = conn.execute(text('''
        DELETE FROM ml_results
        WHERE article_id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                FROM articles
            ) t WHERE t.rn > 1
        )
    '''))
    print(f"  Deleted {result.rowcount} ml_results")

    print("Step 2: Deleting duplicate articles (keeping most recent)...")
    result = conn.execute(text('''
        DELETE FROM articles
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY url ORDER BY extracted_at DESC) as rn
                FROM articles
            ) t WHERE t.rn > 1
        )
    '''))
    print(f"  Deleted {result.rowcount} duplicate articles")

    print("Step 3: Adding unique constraint...")
    conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_url ON articles (url)'))
    print("  ✅ Unique constraint added!")

    conn.close()
    print("\n✅ All done! Extraction can now handle duplicates with ON CONFLICT.")


if __name__ == "__main__":
    clean_duplicates()
