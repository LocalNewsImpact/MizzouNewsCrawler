#!/usr/bin/env python3
"""
Delete wire articles from BigQuery analytics dataset.
These articles were just changed to status='wire' in production PostgreSQL.
"""

import re
from google.cloud import bigquery

# UUID validation pattern
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def extract_article_ids(csv_path):
    """Extract valid article UUIDs from CSV file."""
    article_ids = []
    
    print(f"Reading CSV from: {csv_path}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        for line in f:
            # Skip progress messages and summary lines
            skip_prefixes = (
                'Processing batch', 'Found ', 'Counting', '===',
                'Total articles', 'Articles to mark', 'id,url,title'
            )
            if line.startswith(skip_prefixes):
                continue
            
            # Extract first field (article ID)
            parts = line.split(',', 1)
            if len(parts) > 0:
                potential_id = parts[0].strip()
                if UUID_PATTERN.match(potential_id):
                    article_ids.append(potential_id)
    
    print(f"Extracted {len(article_ids)} valid article IDs")
    return article_ids


def delete_articles_from_bigquery(article_ids, batch_size=1000):
    """Delete articles from BigQuery in batches."""
    
    client = bigquery.Client(project='mizzou-news-crawler')
    dataset_id = 'mizzou_analytics'
    table_id = 'articles'
    full_table = f'{client.project}.{dataset_id}.{table_id}'
    
    print(f"\nDeleting from: {full_table}")
    
    total_deleted = 0
    
    # Process in batches (BigQuery has query size limits)
    for i in range(0, len(article_ids), batch_size):
        batch = article_ids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(article_ids) + batch_size - 1) // batch_size
        
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} articles)...")
        
        # Build DELETE query with IN clause
        id_list = ','.join([f"'{aid}'" for aid in batch])
        query = f"""
            DELETE FROM `{full_table}`
            WHERE id IN ({id_list})
        """
        
        # Execute query
        query_job = client.query(query)
        result = query_job.result()  # Wait for completion
        
        # BigQuery doesn't return rowcount for DELETE, check via separate query
        check_query = f"""
            SELECT COUNT(*) as remaining
            FROM `{full_table}`
            WHERE id IN ({id_list})
        """
        check_job = client.query(check_query)
        remaining = list(check_job.result())[0].remaining
        
        deleted_in_batch = len(batch) - remaining
        total_deleted += deleted_in_batch
        
        print(f"  Deleted {deleted_in_batch} articles")
        print(f"  Remaining in batch: {remaining}")
    
    print(f"\n=== COMPLETE ===")
    print(f"Total articles deleted from BigQuery: {total_deleted}")
    print(f"Total IDs processed: {len(article_ids)}")
    
    # Verify final state
    verify_query = f"""
        SELECT COUNT(*) as count
        FROM `{full_table}`
        WHERE id IN ({','.join([f"'{aid}'" for aid in article_ids[:100]])})
    """
    verify_job = client.query(verify_query)
    sample_remaining = list(verify_job.result())[0].count
    
    if sample_remaining > 0:
        print(f"\nWARNING: {sample_remaining} articles from sample still in BigQuery")
    else:
        print("\n✅ Verification: Sample check confirms deletions successful")


if __name__ == '__main__':
    csv_path = 'production_wire_articles_full_scan.csv'
    
    article_ids = extract_article_ids(csv_path)
    
    if not article_ids:
        print("ERROR: No valid article IDs found in CSV")
        exit(1)
    
    print(f"\nReady to delete {len(article_ids)} wire articles from BigQuery")
    print("These articles were just marked as status='wire' in production PostgreSQL.")
    print("\nProceeding with deletion...")
    
    delete_articles_from_bigquery(article_ids)
