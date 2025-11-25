#!/usr/bin/env python3
"""
Find which wire articles actually exist in BigQuery.

Reads article IDs and checks BigQuery to create a filtered removal list.
"""

import argparse
import csv
import logging
import os
from pathlib import Path

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# BigQuery configuration
BIGQUERY_PROJECT_ID = os.getenv("BIGQUERY_PROJECT_ID", "mizzou-news-crawler")
BIGQUERY_DATASET_ID = os.getenv("BIGQUERY_DATASET_ID", "mizzou_analytics")
BIGQUERY_TABLE_ID = os.getenv("BIGQUERY_TABLE_ID", "articles")


def find_wire_in_bigquery(
    csv_file: Path,
    output_file: Path,
    project_id: str,
    dataset_id: str,
    table_id: str,
    batch_size: int = 1000,
) -> tuple[int, int]:
    """
    Check which articles from CSV exist in BigQuery.
    
    Args:
        csv_file: Path to CSV with article IDs
        output_file: Path to output CSV with only articles found in BigQuery
        project_id: GCP project ID
        dataset_id: BigQuery dataset ID
        table_id: BigQuery table ID
        batch_size: Number of IDs to check per query
    
    Returns:
        Tuple of (total_checked, found_in_bigquery)
    """
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    
    # Read all article IDs from CSV
    articles = []
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            articles.append(row)
    
    total_articles = len(articles)
    logger.info(f"Loaded {total_articles:,} articles from {csv_file}")
    
    # Check in batches
    found_articles = []
    total_found = 0
    
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(articles) + batch_size - 1) // batch_size
        
        article_ids = [row['article_id'] for row in batch]
        
        # Query BigQuery to find which IDs exist
        query = f"""
            SELECT id
            FROM `{table_ref}`
            WHERE id IN UNNEST(@article_ids)
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("article_ids", "STRING", article_ids)
            ]
        )
        
        try:
            results = client.query(query, job_config=job_config).result()
            found_ids = {row.id for row in results}
            
            # Add matching articles to found list
            for article in batch:
                if article['article_id'] in found_ids:
                    found_articles.append(article)
                    total_found += 1
            
            logger.info(
                f"Batch {batch_num}/{total_batches}: "
                f"Found {len(found_ids)}/{len(batch)} in BigQuery "
                f"(Total: {total_found:,})"
            )
            
        except Exception as e:
            logger.error(f"Error processing batch {batch_num}: {e}")
            continue
    
    # Write found articles to output CSV
    if found_articles:
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=found_articles[0].keys())
            writer.writeheader()
            writer.writerows(found_articles)
        
        logger.info(f"✓ Wrote {total_found:,} articles to {output_file}")
    else:
        logger.info("No articles found in BigQuery - nothing to remove")
    
    logger.info("=" * 70)
    logger.info("Summary:")
    logger.info(f"  Total articles checked: {total_articles:,}")
    pct = 100 * total_found / total_articles
    logger.info(f"  Found in BigQuery: {total_found:,} ({pct:.1f}%)")
    logger.info(f"  Not in BigQuery: {total_articles - total_found:,}")
    
    return total_articles, total_found


def main():
    parser = argparse.ArgumentParser(
        description="Find which wire articles exist in BigQuery"
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="CSV file containing article IDs to check",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV file for articles found in BigQuery",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of IDs to check per query (default: 1000)",
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
    
    args = parser.parse_args()
    
    if not args.csv_file.exists():
        logger.error(f"CSV file not found: {args.csv_file}")
        return 1
    
    # Default output filename
    if args.output is None:
        args.output = args.csv_file.parent / f"{args.csv_file.stem}_in_bigquery.csv"
    
    logger.info("Starting BigQuery article lookup")
    logger.info(f"Input CSV: {args.csv_file}")
    logger.info(f"Output CSV: {args.output}")
    logger.info(f"Target: {args.project_id}.{args.dataset_id}.{args.table_id}")
    
    try:
        total, found = find_wire_in_bigquery(
            csv_file=args.csv_file,
            output_file=args.output,
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            batch_size=args.batch_size,
        )
        
        if found > 0:
            logger.info(
                f"\n✓ Use {args.output} to remove {found:,} articles from BigQuery"
            )
        else:
            logger.info("\n✓ No articles need removal from BigQuery")
        
        return 0
        
    except Exception as e:
        logger.error(f"Failed to check BigQuery: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
