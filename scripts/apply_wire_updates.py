#!/usr/bin/env python3
"""Apply wire status updates to production database and delete from BigQuery."""

import csv
import sys
from pathlib import Path
from sqlalchemy import text
from src.models.database import DatabaseManager


def main():
    csv_file = Path("/tmp/production_wire_scan.csv")
    
    if not csv_file.exists():
        print(f"Error: {csv_file} not found")
        return 1
    
    # Load article IDs from CSV
    article_ids = []
    with open(csv_file, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            article_ids.append(row['id'])
    
    print(f"Loaded {len(article_ids)} article IDs from CSV")
    
    if not article_ids:
        print("No articles to update")
        return 0
    
    # Update database
    db = DatabaseManager()
    with db.get_session() as session:
        # Update status to wire
        query = text("""
            UPDATE articles
            SET status = 'wire'
            WHERE id = ANY(:ids)
        """)
        
        result = session.execute(query, {"ids": article_ids})
        session.commit()
        
        updated_count = result.rowcount
        print(f"✓ Updated {updated_count} articles to wire status in PostgreSQL")
    
    # Delete from BigQuery
    try:
        from google.cloud import bigquery
        import os
        
        # Use explicit project for BigQuery operations
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT', 'mizzou-news-rg')
        client = bigquery.Client(project=project_id)
        
        # Split into batches of 1000 for BigQuery
        batch_size = 1000
        total_deleted = 0
        
        for i in range(0, len(article_ids), batch_size):
            batch = article_ids[i:i + batch_size]
            
            # Format IDs for SQL IN clause
            ids_str = "', '".join(batch)
            
            query = f"""
                DELETE FROM `mizzou-news-rg.news_data.articles`
                WHERE id IN ('{ids_str}')
            """
            
            query_job = client.query(query)
            result = query_job.result()
            
            # Count deleted rows (result.total_rows may be None)
            batch_deleted = result.total_rows if result.total_rows else 0
            total_deleted += batch_deleted
            print(f"  Deleted batch {i//batch_size + 1}: {len(batch)} IDs")
        
        print(f"✓ Deleted {total_deleted} articles from BigQuery")
        
    except ImportError:
        print("⚠ BigQuery client not available, skipping BQ deletion")
    except Exception as e:
        print(f"⚠ Error deleting from BigQuery: {e}")
        print(
            "   You may need to run BigQuery deletion manually "
            "or from a pod with BQ permissions"
        )
        # Don't return error - PostgreSQL update already succeeded
        print("\n⚠ PostgreSQL updated, but BigQuery deletion failed")
        return 0
    
    print("\n✓ Complete: Database updated, BigQuery cleaned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
