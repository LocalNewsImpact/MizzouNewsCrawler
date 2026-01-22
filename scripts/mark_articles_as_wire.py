#!/usr/bin/env python3
"""
Mark articles from CSV as wire in PostgreSQL database.
"""

import csv
import sys
from pathlib import Path

from sqlalchemy import text

from src.models.database import DatabaseManager


def load_article_ids_from_csv(csv_path: str) -> set[str]:
    """Load article IDs from the CSV file."""
    article_ids = set()

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            article_id = row['article_id']
            article_ids.add(article_id)

    print(f"Loaded {len(article_ids)} article IDs from CSV")
    return article_ids


def update_postgres_status(article_ids: set[str], dry_run: bool = True) -> int:
    """Update article status to 'wire' in PostgreSQL."""
    db = DatabaseManager()

    with db.get_session() as session:
        # First, verify current status distribution
        result = session.execute(text("""
            SELECT status, COUNT(*) as cnt
            FROM articles
            WHERE id = ANY(:ids)
            GROUP BY status
            ORDER BY cnt DESC
        """), {"ids": list(article_ids)}).fetchall()

        print("\nCurrent status breakdown for these articles:")
        for row in result:
            print(f"  {row[0]}: {row[1]}")

        # Check if any are already wire
        already_wire = session.execute(text("""
            SELECT COUNT(*) as cnt
            FROM articles
            WHERE id = ANY(:ids)
            AND status = 'wire'
        """), {"ids": list(article_ids)}).scalar()

        if already_wire > 0:
            print(f"\n⚠️  {already_wire} articles are already marked as 'wire'")

        if dry_run:
            print("\n[DRY RUN] Would update these articles to status='wire'")
            return 0

        # Update to wire
        result = session.execute(text("""
            UPDATE articles
            SET status = 'wire'
            WHERE id = ANY(:ids)
            AND status != 'wire'
            RETURNING id
        """), {"ids": list(article_ids)})

        updated_count = result.rowcount
        session.commit()

        print(f"\n✓ Updated {updated_count} articles to status='wire' in PostgreSQL")
        return updated_count


def main():
    if len(sys.argv) < 2:
        print("Usage: python mark_articles_as_wire.py <csv_file> [--execute]")
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
        response = input("\nAre you sure you want to mark these articles as wire? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted")
            sys.exit(0)

    # Load article IDs
    article_ids = load_article_ids_from_csv(csv_path)

    if not article_ids:
        print("No article IDs found in CSV")
        sys.exit(1)

    # Update PostgreSQL
    updated = update_postgres_status(article_ids, dry_run=dry_run)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"CSV articles: {len(article_ids)}")
    if dry_run:
        print(f"Would update: {len(article_ids)} articles to status='wire'")
        print("\nRerun with --execute to apply changes")
    else:
        print(f"PostgreSQL updated: {updated} articles")
        print("\n✓ Articles marked as wire successfully")
        print("\nNext: Delete these articles from BigQuery using delete_wire_articles_from_bigquery.py")


if __name__ == '__main__':
    main()
