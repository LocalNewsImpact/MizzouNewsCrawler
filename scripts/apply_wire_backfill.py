#!/usr/bin/env python3
"""
Apply wire detection backfill results:
1. Update article status to 'wire' in PostgreSQL
2. Delete articles from BigQuery
"""

import csv
import json
import sys
from pathlib import Path

from google.cloud import bigquery
from sqlalchemy import text

from src.models.database import DatabaseManager


def load_article_payloads_from_csv(csv_path: str) -> dict[str, dict]:
    """Load article IDs and wire payloads from the CSV file."""
    payloads: dict[str, dict] = {}

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            article_id = row['article_id']
            provider = row.get("detected_service") or row.get("wire_service") or "Unknown"
            detection_tier = row.get("detection_tier") or "unknown"
            confidence = row.get("confidence")

            payloads[article_id] = {
                "provider": provider,
                "detection_method": "backfill_csv",
                "detection_tier": detection_tier,
                "confidence": float(confidence) if confidence not in (None, "") else None,
                "detected_at": row.get("detected_at"),
            }

    print(f"Loaded {len(payloads)} article IDs from CSV")
    return payloads


def update_postgres_status(article_payloads: dict[str, dict], dry_run: bool = True) -> int:
    """Update article status to 'wire' in PostgreSQL and persist wire payload."""
    db = DatabaseManager()
    article_ids = list(article_payloads.keys())

    with db.get_session() as session:
        # First, verify these are all currently 'labeled'
        result = session.execute(text("""
            SELECT status, COUNT(*) as cnt
            FROM articles
            WHERE id = ANY(:ids)
            GROUP BY status
        """), {"ids": list(article_ids)}).fetchall()

        print("\nCurrent status breakdown:")
        for row in result:
            print(f"  {row[0]}: {row[1]}")

        if dry_run:
            print("\n[DRY RUN] Would update these articles to status='wire'")
            return 0

        # Update to wire
        updated_count = 0
        for article_id, payload in article_payloads.items():
            if not payload.get("provider"):
                continue
            result = session.execute(text("""
                UPDATE articles
                SET status = 'wire',
                    wire = :wire_payload,
                    wire_check_status = 'complete',
                    wire_check_error = NULL,
                    wire_check_metadata = NULL
                WHERE id = :id
                AND status = 'labeled' AND wire_check_status = 'complete'
                RETURNING id
            """), {
                "id": article_id,
                "wire_payload": json.dumps(payload),
            })

            if result.rowcount:
                updated_count += 1

        session.commit()

        print(f"\n✓ Updated {updated_count} articles to status='wire' in PostgreSQL")
        return updated_count


def delete_from_bigquery(article_ids: set[str], dry_run: bool = True) -> int:
    """Delete articles from BigQuery."""
    client = bigquery.Client()

    # Split into batches of 1000 for BigQuery query limits
    batch_size = 1000
    article_id_list = list(article_ids)
    total_deleted = 0

    for i in range(0, len(article_id_list), batch_size):
        batch = article_id_list[i:i + batch_size]

        # Create parameterized query
        id_params = ','.join([f"'{aid}'" for aid in batch])

        # Check what would be deleted
        count_query = f"""
            SELECT COUNT(*) as cnt
            FROM `mizzou-news-375903.mizzou_articles.articles`
            WHERE article_id IN ({id_params})
        """

        count_result = client.query(count_query).result()
        batch_count = list(count_result)[0]['cnt']

        print(f"\nBatch {i//batch_size + 1}: {batch_count} articles found in BigQuery")

        if dry_run:
            print(f"[DRY RUN] Would delete {batch_count} articles from BigQuery")
            total_deleted += batch_count
            continue

        # Execute delete
        delete_query = f"""
            DELETE FROM `mizzou-news-375903.mizzou_articles.articles`
            WHERE article_id IN ({id_params})
        """

        job = client.query(delete_query)
        job.result()  # Wait for completion

        print(f"✓ Deleted {batch_count} articles from BigQuery")
        total_deleted += batch_count

    return total_deleted


def main():
    if len(sys.argv) < 2:
        print("Usage: python apply_wire_backfill.py <csv_file> [--execute]")
        print("\nBy default, runs in DRY RUN mode. Use --execute to apply changes.")
        sys.exit(1)

    csv_path = sys.argv[1]
    dry_run = '--execute' not in sys.argv

    if not Path(csv_path).exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    if dry_run:
        print("=" * 80)
        print("DRY RUN MODE - No changes will be made")
        print("Add --execute flag to apply changes")
        print("=" * 80)
    else:
        print("=" * 80)
        print("EXECUTE MODE - Changes will be applied!")
        print("=" * 80)

    # Load article IDs
    article_payloads = load_article_payloads_from_csv(csv_path)

    if not article_payloads:
        print("No article IDs found in CSV")
        sys.exit(1)

    # Update PostgreSQL
    print("\n" + "=" * 80)
    print("STEP 1: Update PostgreSQL status to 'wire'")
    print("=" * 80)
    postgres_updated = update_postgres_status(article_payloads, dry_run=dry_run)

    # Delete from BigQuery
    print("\n" + "=" * 80)
    print("STEP 2: Delete from BigQuery")
    print("=" * 80)
    bq_deleted = delete_from_bigquery(article_ids, dry_run=dry_run)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"CSV articles: {len(article_ids)}")
    if dry_run:
        print(f"Would update PostgreSQL: {len(article_ids)} articles")
        print(f"Would delete BigQuery: {bq_deleted} articles")
        print("\nRerun with --execute to apply changes")
    else:
        print(f"PostgreSQL updated: {postgres_updated} articles")
        print(f"BigQuery deleted: {bq_deleted} articles")
        print("\n✓ Wire backfill applied successfully")


if __name__ == '__main__':
    main()
