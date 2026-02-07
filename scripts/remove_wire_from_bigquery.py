#!/usr/bin/env python3
"""
Remove articles from BigQuery that are newly marked as WIRE.

Inputs:
- IDs CSV from promotion script (columns: article_id[, url, host])

Behavior:
- Counts occurrences of IDs in BigQuery tables (preview)
- Deletes matching rows in target tables when not in --dry-run

Args:
- --ids-file: Path to CSV with article IDs (first column is the id)
- --project: GCP project (default: mizzou-news-crawler)
- --dataset: BigQuery dataset (default: mizzou_analytics)
- --tables: Tables to delete from (default: articles,cin_labels,entities)
- --chunk-size: IDs per delete batch (default: 5000)
- --dry-run: Preview counts only, no delete
- --progress-interval: Progress print frequency (default: 1 batch)

Requires google-cloud-bigquery and application default credentials.
"""

import argparse
import csv
from typing import List

from google.cloud import bigquery


def read_ids(path: str) -> List[str]:
    ids = []
    with open(path, "r", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if not row:
                continue
            aid = row[0].strip()
            if aid:
                ids.append(aid)
    return ids


def chunked(lst: List[str], size: int) -> List[List[str]]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def count_ids_in_table(client: bigquery.Client, project: str, dataset: str, table: str, ids: List[str]) -> int:
    col = "article_id" if table != "articles" else "id"
    sql = f"SELECT COUNT(1) AS c FROM `{project}.{dataset}.{table}` WHERE {col} IN UNNEST(@ids)"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)]
    )
    job = client.query(sql, job_config=job_config)
    result = list(job.result())
    return int(result[0]["c"]) if result else 0


def delete_ids_in_table(client: bigquery.Client, project: str, dataset: str, table: str, ids: List[str]) -> None:
    col = "article_id" if table != "articles" else "id"
    sql = f"DELETE FROM `{project}.{dataset}.{table}` WHERE {col} IN UNNEST(@ids)"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)]
    )
    job = client.query(sql, job_config=job_config)
    job.result()  # Wait for completion (BigQuery doesn't return deleted count)
    return None


def main():
    p = argparse.ArgumentParser(description="Remove newly promoted wire IDs from BigQuery")
    p.add_argument("--ids-file", required=True, help="CSV file with article IDs (first column)")
    p.add_argument("--project", default="mizzou-news-crawler", help="GCP project")
    p.add_argument("--dataset", default="mizzou_analytics", help="BigQuery dataset")
    p.add_argument(
        "--tables",
        default="articles,cin_labels,entities",
        help="Comma-separated table list to delete from",
    )
    p.add_argument("--chunk-size", type=int, default=5000, help="IDs per batch")
    p.add_argument("--dry-run", action="store_true", help="Preview only; no deletes")
    p.add_argument("--progress-interval", type=int, default=1, help="Print progress every N batches")
    args = p.parse_args()

    ids = read_ids(args.ids_file)
    if not ids:
        print("No IDs found in CSV; nothing to do.")
        return
    print(f"Loaded {len(ids)} IDs from {args.ids_file}")

    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    client = bigquery.Client(project=args.project)
    batches = chunked(ids, args.chunk_size)
    print(f"Processing {len(batches)} batches of size ~{args.chunk_size}")

    total_present = 0
    total_deleted = 0
    for bi, batch in enumerate(batches, 1):
        present_counts = {}
        for table in tables:
            c = count_ids_in_table(client, args.project, args.dataset, table, batch)
            present_counts[table] = c
        total_present += sum(present_counts.values())

        if args.dry_run:
            if bi % args.progress_interval == 0:
                print(f"[DRY] Batch {bi}/{len(batches)} present: {present_counts}")
            continue

        # Delete in each table (approximate deleted = rows found in this batch per table)
        for table in tables:
            if present_counts[table] > 0:
                delete_ids_in_table(client, args.project, args.dataset, table, batch)
                total_deleted += present_counts[table]
        if bi % args.progress_interval == 0:
            print(f"[LIVE] Batch {bi}/{len(batches)} deleted approx: {sum(present_counts.values())}")

    mode = "DRY" if args.dry_run else "LIVE"
    print(f"[{mode}] Total present across tables: {total_present}")
    if not args.dry_run:
        print(f"[LIVE] Approx rows deleted across tables: {total_deleted}")


if __name__ == "__main__":
    main()
