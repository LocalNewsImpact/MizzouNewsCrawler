#!/usr/bin/env python3
"""
Fix wire detection bug where articles were marked as 'wire' without MediaCloud checking.

Issue: Articles extracted since Dec 21 have:
- wire_check_status='complete'
- wire_check_attempted_at=NULL (MediaCloud never ran)
- status='wire' (incorrectly marked as syndicated)

This script resets affected articles to allow proper MediaCloud verification.
"""

from src.models.database import DatabaseManager
from sqlalchemy import text
import sys

def main():
    db = DatabaseManager()

    # Query affected articles
    with db.get_session() as session:
        print("Querying affected articles...")
        affected = session.execute(text('''
            SELECT
                id,
                url,
                title,
                status,
                extracted_at
            FROM articles
            WHERE wire_check_status = 'complete'
            AND wire_check_attempted_at IS NULL
            AND status = 'wire'
            AND extracted_at >= '2025-12-21'
            ORDER BY extracted_at DESC
            LIMIT 10
        ''')).fetchall()

        print(f"\nSample of 10 affected articles:")
        print("=" * 100)
        for row in affected:
            print(f"{row[3]:10s} | {row[4]} | {row[2][:60]}")

        total = session.execute(text('''
            SELECT COUNT(*)
            FROM articles
            WHERE wire_check_status = 'complete'
            AND wire_check_attempted_at IS NULL
            AND status = 'wire'
            AND extracted_at >= '2025-12-21'
        ''')).scalar()

        print(f"\nTotal affected: {total} articles")
        print("\nThese articles will be reset to:")
        print("  - status: 'extracted'")
        print("  - wire_check_status: 'pending'")
        print("  - wire_check_attempted_at: NULL (already NULL)")
        print("  - wire_check_metadata: NULL")
        print("\nMediaCloud will then re-check them in the normal processing flow.")

        response = input("\nProceed with fix? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return 1

        print("\nResetting articles...")
        result = session.execute(text('''
            UPDATE articles
            SET
                status = 'extracted',
                wire_check_status = 'pending',
                wire_check_attempted_at = NULL,
                wire_check_metadata = NULL,
                wire_check_error = NULL
            WHERE wire_check_status = 'complete'
            AND wire_check_attempted_at IS NULL
            AND status = 'wire'
            AND extracted_at >= '2025-12-21'
        '''))

        session.commit()
        print(f"✓ Reset {result.rowcount} articles")

        # Also update candidate_links status
        print("\nUpdating candidate_links status...")
        result2 = session.execute(text('''
            UPDATE candidate_links cl
            SET status = 'article'
            FROM articles a
            WHERE cl.id = a.candidate_link_id
            AND a.status = 'extracted'
            AND a.wire_check_status = 'pending'
            AND cl.status = 'wire'
        '''))

        session.commit()
        print(f"✓ Updated {result2.rowcount} candidate_links")

        print("\n✓ Fix complete! Articles will be re-checked by MediaCloud processor.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
