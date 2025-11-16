#!/usr/bin/env python3
"""Delete wire articles from BigQuery."""

import csv
import sys
from pathlib import Path


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
        print("No articles to delete")
        return 0
    
    # Delete from BigQuery
    try:
        from google.cloud import bigquery
        import os
        
        # Use explicit project for BigQuery operations
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT', 'mizzou-news-rg')
        print(f"Using BigQuery project: {project_id}")
        
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
            
            print(
                f"Deleting batch {i//batch_size + 1} "
                f"({len(batch)} IDs)..."
            )
            query_job = client.query(query)
            result = query_job.result()
            
            # Count deleted rows (result.total_rows may be None)
            batch_deleted = result.total_rows if result.total_rows else 0
            total_deleted += batch_deleted
            print(f"  ✓ Deleted {batch_deleted} rows")
        
        print(f"\n✓ Total deleted from BigQuery: {total_deleted} articles")
        
    except ImportError:
        print("⚠ BigQuery client not available")
        return 1
    except Exception as e:
        print(f"⚠ Error deleting from BigQuery: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
