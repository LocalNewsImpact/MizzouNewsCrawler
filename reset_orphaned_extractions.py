#!/usr/bin/env python
"""Reset candidate_links that were marked as extracted but failed to write to articles table.

This script identifies candidate_links that have status 'extracted', 'labeled', 'wire', or 'obituary'
but have no corresponding entry in the articles table (due to the Cloud SQL Connector async/await bug
that caused silent commit failures from Oct 22-24, 2025).

It resets their status back to 'verified' so they can be re-extracted.
"""

import sys
from src.models.database import DatabaseManager
from sqlalchemy import text

def main():
    db = DatabaseManager()
    
    # Count orphaned candidate_links
    count_query = """
    SELECT COUNT(*)
    FROM candidate_links cl
    LEFT JOIN articles a ON a.url = cl.url
    WHERE cl.status IN ('extracted', 'labeled', 'wire', 'obituary')
      AND cl.fetched_at >= '2025-10-22 19:54:00'
      AND a.id IS NULL
    """
    
    result = db.session.execute(text(count_query))
    orphaned_count = result.scalar()
    
    print(f"Found {orphaned_count} candidate_links marked as extracted but not in articles table")
    print("(since 2025-10-22 19:54:00 when extraction started failing)")
    
    if orphaned_count == 0:
        print("Nothing to reset!")
        return 0
    
    # Show breakdown by status
    breakdown_query = """
    SELECT cl.status, COUNT(*) as count
    FROM candidate_links cl
    LEFT JOIN articles a ON a.url = cl.url
    WHERE cl.status IN ('extracted', 'labeled', 'wire', 'obituary')
      AND cl.fetched_at >= '2025-10-22 19:54:00'
      AND a.id IS NULL
    GROUP BY cl.status
    ORDER BY count DESC
    """
    
    result = db.session.execute(text(breakdown_query))
    print("\nBreakdown by status:")
    for row in result:
        print(f"  {row[0]}: {row[1]}")
    
    # Ask for confirmation
    response = input(f"\nReset {orphaned_count} candidate_links to 'verified' status? (yes/no): ")
    if response.lower() not in ('yes', 'y'):
        print("Aborted.")
        return 1
    
    # Reset the orphaned links
    reset_query = """
    UPDATE candidate_links
    SET status = 'verified'
    WHERE id IN (
        SELECT cl.id
        FROM candidate_links cl
        LEFT JOIN articles a ON a.url = cl.url
        WHERE cl.status IN ('extracted', 'labeled', 'wire', 'obituary')
          AND cl.fetched_at >= '2025-10-22 19:54:00'
          AND a.id IS NULL
    )
    """
    
    result = db.session.execute(text(reset_query))
    db.session.commit()
    rows_updated = result.rowcount
    
    print(f"\n✅ Reset {rows_updated} candidate_links to 'verified' status")
    print("They will be re-extracted in the next extraction workflow.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
