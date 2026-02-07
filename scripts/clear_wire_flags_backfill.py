#!/usr/bin/env python3
"""
Clear all wire detection flags for ABC 17 and News-Press NOW articles.

This resets articles to a clean state so the processor can re-run
wire detection with the FIXED code (without the ABC 17 footer bug).

Steps:
1. Clear wire column (set to NULL)
2. Clear wire_check_status 
3. Set status back to 'cleaned' so processor will re-evaluate
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models.database import DatabaseManager
from sqlalchemy import text


def main():
    """Clear wire flags and reset status for re-processing."""
    import sys
    
    # Check for --force flag
    force = "--force" in sys.argv
    
    db = DatabaseManager()
    
    print("=" * 80)
    print("CLEAR WIRE FLAGS BACKFILL")
    print("=" * 80)
    print()
    
    # Get count of affected articles
    print("Fetching articles to reset...")
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT COUNT(*)
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE cl.source IN ('ABC 17 KMIZ News', 'News Press Now')
            AND a.status IN ('wire', 'local', 'cleaned', 'labeled')
        """))
        total_count = result.scalar()
    
    print(f"Found {total_count} articles to reset")
    print()
    
    # Show breakdown by current status
    with db.get_session() as session:
        result = session.execute(text("""
            SELECT a.status, COUNT(*) as cnt
            FROM articles a
            JOIN candidate_links cl ON a.candidate_link_id = cl.id
            WHERE cl.source IN ('ABC 17 KMIZ News', 'News Press Now')
            AND a.status IN ('wire', 'local', 'cleaned', 'labeled')
            GROUP BY a.status
            ORDER BY cnt DESC
        """))
        print("Current status breakdown:")
        for row in result:
            print(f"  {row[0]}: {row[1]}")
    print()
    
    # Ask for confirmation
    print(f"⚠️  This will:")
    print(f"  1. Clear wire column (set to NULL)")
    print(f"  2. Clear wire_check_status (set to NULL)")
    print(f"  3. Set status='extracted' for all {total_count} articles")
    print(f"  4. Processor will then re-run cleaning + wire detection with FIXED code")
    print()
    
    if not force:
        response = input("Continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return
    else:
        print("Running with --force flag (skipping confirmation)")
        print()
    
    # Clear wire flags and reset status
    print("\nClearing wire flags and resetting status to 'extracted'...")
    with db.get_session() as session:
        result = session.execute(text("""
            UPDATE articles a
            SET 
                wire = NULL,
                wire_check_status = NULL,
                status = 'extracted'
            FROM candidate_links cl
            WHERE a.candidate_link_id = cl.id
            AND cl.source IN ('ABC 17 KMIZ News', 'News Press Now')
            AND a.status IN ('wire', 'local', 'cleaned', 'labeled')
        """))
        session.commit()
        updated_count = result.rowcount
    
    print(f"✅ Updated {updated_count} articles")
    print()
    print("=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print()
    print("The processor will now re-run wire detection on these articles.")
    print("Monitor processor logs to see wire detection happening:")
    print("  kubectl logs -n production -l app=mizzou-processor --tail=100 -f")
    print()
    print("After processor runs, check results:")
    print("  SELECT status, COUNT(*) FROM articles a")
    print("  JOIN candidate_links cl ON a.candidate_link_id = cl.id")
    print("  WHERE cl.source IN ('ABC 17 KMIZ News', 'News Press Now')")
    print("  GROUP BY status;")
    print()


if __name__ == "__main__":
    main()
