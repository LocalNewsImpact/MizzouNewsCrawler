#!/usr/bin/env python3
"""
Report date range and daily distribution in BigQuery for matched article IDs.
- Loads IDs from CSV (header: article_id)
- Queries dataset.table `articles` and reports:
  * MIN/MAX of publish_date and extracted_at
  * Daily counts using publish_date (fallback to extracted_at)
"""
import argparse
import csv
from typing import List

from google.cloud import bigquery


def load_ids(path: str) -> List[str]:
    ids = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and 'article_id' in reader.fieldnames:
            for row in reader:
                v = row.get('article_id')
                if v:
                    ids.append(v.strip())
        else:
            f.seek(0)
            r = csv.reader(f)
            header = next(r, None)
            for row in r:
                if row:
                    ids.append(row[0].strip())
    return ids


def main():
    parser = argparse.ArgumentParser(description='BigQuery date range for matched IDs')
    parser.add_argument('--csv', required=True, help='CSV of article IDs (header: article_id)')
    parser.add_argument('--project', required=True, help='GCP Project ID')
    parser.add_argument('--dataset', required=True, help='BigQuery dataset name')
    parser.add_argument('--table', default='articles', help='Articles table name (default: articles)')
    parser.add_argument('--out-daily', default='data/bq_matched_daily_counts.csv', help='Output CSV for daily counts')
    args = parser.parse_args()

    client = bigquery.Client(project=args.project)
    ids = load_ids(args.csv)

    table_ref = f"{args.project}.{args.dataset}.{args.table}"

    # Check schema to determine columns available
    table = client.get_table(table_ref)
    column_names = {field.name for field in table.schema}
    has_publish_date = 'publish_date' in column_names
    has_extracted_at = 'extracted_at' in column_names

    # Range query
    range_sql = None
    if has_publish_date and has_extracted_at:
        range_sql = f"""
            SELECT
              MIN(CAST(publish_date AS TIMESTAMP)) AS min_publish_ts,
              MAX(CAST(publish_date AS TIMESTAMP)) AS max_publish_ts,
              MIN(extracted_at) AS min_extracted_at,
              MAX(extracted_at) AS max_extracted_at,
              COUNT(*) AS matched_cnt
            FROM `{table_ref}`
            WHERE id IN UNNEST(@ids)
        """
    elif has_publish_date:
        range_sql = f"""
            SELECT
              MIN(CAST(publish_date AS TIMESTAMP)) AS min_publish_ts,
              MAX(CAST(publish_date AS TIMESTAMP)) AS max_publish_ts,
              NULL AS min_extracted_at,
              NULL AS max_extracted_at,
              COUNT(*) AS matched_cnt
            FROM `{table_ref}`
            WHERE id IN UNNEST(@ids)
        """
    elif has_extracted_at:
        range_sql = f"""
            SELECT
              NULL AS min_publish_ts,
              NULL AS max_publish_ts,
              MIN(extracted_at) AS min_extracted_at,
              MAX(extracted_at) AS max_extracted_at,
              COUNT(*) AS matched_cnt
            FROM `{table_ref}`
            WHERE id IN UNNEST(@ids)
        """
    else:
        print('Neither publish_date nor extracted_at columns found.')
        return

    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter('ids', 'STRING', ids)]
    )
    range_job = client.query(range_sql, job_config=job_config)
    range_res = list(range_job.result())[0]

    print(f"Matched rows: {range_res.matched_cnt}")
    print(f"Min publish_ts: {range_res.min_publish_ts}")
    print(f"Max publish_ts: {range_res.max_publish_ts}")
    print(f"Min extracted_at: {range_res.min_extracted_at}")
    print(f"Max extracted_at: {range_res.max_extracted_at}")

    # Daily counts (prefer publish_date, fallback to extracted_at)
    if has_publish_date:
        daily_sql = f"""
            SELECT DATE(publish_date) AS day, COUNT(*) AS cnt
            FROM `{table_ref}`
            WHERE id IN UNNEST(@ids)
            GROUP BY day
            ORDER BY day
        """
    else:
        daily_sql = f"""
            SELECT DATE(extracted_at) AS day, COUNT(*) AS cnt
            FROM `{table_ref}`
            WHERE id IN UNNEST(@ids)
            GROUP BY day
            ORDER BY day
        """

    daily_job = client.query(daily_sql, job_config=job_config)
    rows = list(daily_job.result())

    # Write CSV
    with open(args.out_daily, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['day', 'count'])
        for r in rows:
            w.writerow([r.day, r.cnt])

    print(f"Wrote daily counts to {args.out_daily}")


if __name__ == '__main__':
    main()
