#!/usr/bin/env python3
"""
Remove wire articles from BigQuery.

Reads a CSV file containing article IDs and removes them from the BigQuery dataset.
Handles articles that may have already been removed (404s).
"""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

from google.api_core import exceptions
from google.cloud import bigquery

# BigQuery configuration from environment
BIGQUERY_PROJECT_ID = os.getenv("BIGQUERY_PROJECT_ID", "mizzou-news-crawler")
BIGQUERY_DATASET_ID = os.getenv("BIGQUERY_DATASET_ID", "mizzou_analytics")
BIGQUERY_TABLE_ID = os.getenv("BIGQUERY_TABLE_ID", "articles")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def remove_articles_from_bigquery(
    csv_file: Path,
    project_id: str,
    dataset_id: str,
    table_id: str,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """
    Remove articles from BigQuery by article ID.
    
    Args:
        csv_file: Path to CSV file containing article IDs (one per line, first column)
        project_id: GCP project ID
        dataset_id: BigQuery dataset ID
        table_id: BigQuery table ID
        dry_run: If True, only report what would be deleted
    
    Returns:
        Tuple of (total_ids, deleted_count, not_found_count)
    """
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    
    # Read article IDs from CSV
    article_ids = []
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row and 'article_id' in row:
                article_ids.append(row['article_id'])
    
    total_ids = len(article_ids)
    logger.info(f"Loaded {total_ids:,} article IDs from {csv_file}")
    
    if dry_run:
        logger.info("DRY RUN: No articles will be deleted")
        
        # Check how many exist in BigQuery
        query = f"""
            SELECT COUNT(*) as cnt
            FROM `{table_ref}`
            WHERE id IN UNNEST(@article_ids)
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("article_ids", "STRING", article_ids)
            ]
        )
        
        try:
            result = client.query(query, job_config=job_config).result()
            found_count = list(result)[0].cnt
            logger.info(f"Found {found_count:,} articles in BigQuery")
            logger.info(
                f"Not found: {total_ids - found_count:,} (likely already removed)"
            )
            return total_ids, 0, total_ids - found_count
        except Exception as e:
            logger.error(f"Error checking BigQuery: {e}")
            return total_ids, 0, 0
    
    # Process in batches of 1000 to avoid query size limits
    batch_size = 1000
    deleted_count = 0
    not_found_count = 0
    
    for i in range(0, len(article_ids), batch_size):
        batch = article_ids[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(article_ids) + batch_size - 1) // batch_size
        
        # First check how many exist in this batch
        check_query = f"""
            SELECT COUNT(*) as cnt
            FROM `{table_ref}`
            WHERE id IN UNNEST(@article_ids)
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("article_ids", "STRING", batch)
            ]
        )
        
        try:
            result = client.query(check_query, job_config=job_config).result()
            found_in_batch = list(result)[0].cnt
            not_found_in_batch = len(batch) - found_in_batch
            not_found_count += not_found_in_batch
            
            if found_in_batch == 0:
                logger.info(
                    f"Batch {batch_num}/{total_batches}: "
                    f"No articles found (all {len(batch)} already removed)"
                )
                continue
            
            # Delete the articles
            delete_query = f"""
                DELETE FROM `{table_ref}`
                WHERE id IN UNNEST(@article_ids)
            """
            
            client.query(delete_query, job_config=job_config).result()
            deleted_count += found_in_batch
            
            logger.info(
                f"Batch {batch_num}/{total_batches}: "
                f"Deleted {found_in_batch}, "
                f"Not found {not_found_in_batch}, "
                f"Total deleted: {deleted_count:,}"
            )
            
        except exceptions.NotFound:
            logger.warning(f"Table {table_ref} not found")
            not_found_count += len(batch)
        except Exception as e:
            logger.error(f"Error processing batch {batch_num}: {e}")
            # Continue with next batch
            continue
    
    logger.info("=" * 70)
    logger.info("Removal complete:")
    logger.info(f"  Total IDs processed: {total_ids:,}")
    logger.info(f"  Deleted from BigQuery: {deleted_count:,}")
    logger.info(f"  Not found (already removed): {not_found_count:,}")
    
    return total_ids, deleted_count, not_found_count


def main():
    parser = argparse.ArgumentParser(
        description="Remove wire articles from BigQuery"
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="CSV file containing article IDs to remove",
    )
    parser.add_argument(
        "--project-id",
        default=BIGQUERY_PROJECT_ID,
        help="GCP project ID",
    )
    parser.add_argument(
        "--dataset-id",
        default=BIGQUERY_DATASET_ID,
        help="BigQuery dataset ID",
    )
    parser.add_argument(
        "--table-id",
        default=BIGQUERY_TABLE_ID,
        help="BigQuery table ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check what would be deleted without deleting",
    )
    
    args = parser.parse_args()
    
    if not args.csv_file.exists():
        logger.error(f"CSV file not found: {args.csv_file}")
        sys.exit(1)
    
    logger.info("Starting BigQuery wire article removal")
    logger.info(f"CSV file: {args.csv_file}")
    logger.info(f"Target: {args.project_id}.{args.dataset_id}.{args.table_id}")
    logger.info(f"Dry run: {args.dry_run}")
    
    try:
        total, deleted, not_found = remove_articles_from_bigquery(
            csv_file=args.csv_file,
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            dry_run=args.dry_run,
        )
        
        if args.dry_run:
            logger.info("DRY RUN: No changes were made to BigQuery")
        
    except Exception as e:
        logger.error(f"Failed to remove articles: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
