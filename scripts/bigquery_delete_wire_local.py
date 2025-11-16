#!/usr/bin/env python3
"""
Delete wire articles from BigQuery - LOCAL EXECUTION ONLY.

This script should be run from your local machine with proper GCP authentication.
Run: gcloud auth application-default login
Then: python scripts/bigquery_delete_wire_local.py
"""

import csv
import sys
from pathlib import Path


def main():
    csv_file = Path("/tmp/production_wire_scan.csv")
    
    if not csv_file.exists():
        print(f"Error: {csv_file} not found")
        print("Please copy the CSV from production first:")
        print(
            "  POD=$(kubectl get pods -n production -l app=mizzou-processor "
            "-o jsonpath='{.items[0].metadata.name}')"
        )
        print(
            "  kubectl cp production/$POD:/tmp/production_wire_scan.csv "
            "/tmp/production_wire_scan.csv"
        )
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
        
        # The client will use application default credentials
        # Make sure you've run: gcloud auth application-default login
        client = bigquery.Client()
        
        print(f"Using BigQuery project: {client.project}")
        print(
            "\nDeleting from: mizzou-news-rg.news_data.articles "
            f"({len(article_ids)} articles)"
        )
        
        # Confirm before proceeding
        response = input("\nProceed with deletion? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted")
            return 0
        
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
                f"\nDeleting batch {i//batch_size + 1} "
                f"({len(batch)} IDs)..."
            )
            query_job = client.query(query)
            result = query_job.result()
            
            # Count deleted rows (num_dml_affected_rows for DELETE)
            batch_deleted = result.num_dml_affected_rows or 0
            total_deleted += batch_deleted
            print(f"  ✓ Deleted {batch_deleted} rows from BigQuery")
        
        print(f"\n✓ Total deleted from BigQuery: {total_deleted} articles")
        print("\n✓ Complete!")
        print(
            "  - PostgreSQL: 940 articles updated to wire status"
        )
        print(f"  - BigQuery: {total_deleted} articles deleted")
        
    except ImportError:
        print("\n⚠ BigQuery client not available")
        print("Install with: pip install google-cloud-bigquery")
        return 1
    except Exception as e:
        print(f"\n⚠ Error deleting from BigQuery: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
