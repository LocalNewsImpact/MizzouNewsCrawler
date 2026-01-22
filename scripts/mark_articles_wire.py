#!/usr/bin/env python3
"""
Mark articles from CSV as wire status in PostgreSQL database.
"""
import csv
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import DatabaseManager
from sqlalchemy import text


def main():
    csv_file = "/Users/kiesowd/Downloads/wire_backfill_REMOVE_20251127_181457.csv"

    # Read article IDs from CSV
    article_ids = []
    with open(csv_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            article_ids.append(row['article_id'])

    print(f"Loaded {len(article_ids)} article IDs from CSV")

    db = DatabaseManager()
    with db.get_session() as session:
        # Check current status
        result = session.execute(text("""
            SELECT status, COUNT(*)
            FROM articles
            WHERE id = ANY(:ids)
            GROUP BY status
        """), {"ids": article_ids}).fetchall()

        print("\nCurrent status breakdown:")
        for status, count in result:
            print(f"  {status}: {count}")

        # Update to wire
        print(f"\nUpdating {len(article_ids)} articles to status='wire'...")
        result = session.execute(text("""
            UPDATE articles
            SET status = 'wire'
            WHERE id = ANY(:ids)
            AND status != 'wire'
        """), {"ids": article_ids})

        updated_count = result.rowcount
        session.commit()

        print(f"✓ Updated {updated_count} articles to wire status")

        # Verify
        wire_count = session.execute(text("""
            SELECT COUNT(*)
            FROM articles
            WHERE id = ANY(:ids) AND status = 'wire'
        """), {"ids": article_ids}).scalar()

        print(f"✓ Verified: {wire_count} articles now have status='wire'")


if __name__ == "__main__":
    main()
