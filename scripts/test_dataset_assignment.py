#!/usr/bin/env python3
"""
Test script to verify dataset assignment works correctly.

This script:
1. Runs a small discovery job with explicit dataset parameter
2. Verifies that new candidate_links have proper dataset_id
3. Checks that no new NULL values were created
"""

import subprocess
import sys
from datetime import datetime, timedelta

from src.models.database import DatabaseManager
from sqlalchemy import text


def get_null_count(db):
    """Get count of candidate_links with NULL dataset_id."""
    return db.session.execute(text(
        "SELECT COUNT(*) FROM candidate_links WHERE dataset_id IS NULL"
    )).scalar()


def get_recent_links_count(db, minutes=5):
    """Get count of candidate_links discovered in last N minutes."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    return db.session.execute(text(
        """
        SELECT COUNT(*)
        FROM candidate_links
        WHERE discovered_at > :cutoff
        """
    ), {"cutoff": cutoff}).scalar()


def main():
    print("=" * 80)
    print("TESTING DATASET ASSIGNMENT FIX")
    print("=" * 80)
    
    with DatabaseManager() as db:
        # Record state before test
        null_before = get_null_count(db)
        print(f"\n📊 Before test:")
        print(f"   NULL dataset_id count: {null_before}")
        
        # Run small discovery with dataset parameter
        print(f"\n🔄 Running discovery with dataset parameter...")
        print(f"   Command: discover-urls --dataset 'Publisher Links from publinks.csv'")
        print(f"            --source-limit 3 --max-articles 5")
        
        result = subprocess.run([
            sys.executable, "-m", "src.cli.main",
            "discover-urls",
            "--dataset", "Publisher Links from publinks.csv",
            "--source-limit", "3",
            "--max-articles", "5",
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"\n❌ Discovery failed!")
            print(f"   STDOUT: {result.stdout}")
            print(f"   STDERR: {result.stderr}")
            return 1
        
        print(f"✅ Discovery completed successfully")
        
        # Check state after test
        null_after = get_null_count(db)
        recent_links = get_recent_links_count(db, minutes=5)
        
        print(f"\n📊 After test:")
        print(f"   NULL dataset_id count: {null_after}")
        print(f"   New links discovered: {recent_links}")
        
        # Verify no new NULLs were created
        if null_after > null_before:
            print(f"\n❌ FAIL: {null_after - null_before} new NULL values created!")
            print(f"   This indicates the dataset parameter is not working correctly.")
            return 1
        
        if null_after < null_before:
            print(f"\n✅ BONUS: {null_before - null_after} NULL values were fixed!")
        
        if null_after == null_before:
            print(f"\n✅ PASS: No new NULL values created")
        
        # Check that new links have proper dataset_id
        if recent_links > 0:
            null_recent = db.session.execute(text(
                """
                SELECT COUNT(*)
                FROM candidate_links
                WHERE discovered_at > :cutoff
                  AND dataset_id IS NULL
                """
            ), {"cutoff": datetime.utcnow() - timedelta(minutes=5)}).scalar()
            
            if null_recent > 0:
                print(f"\n❌ WARNING: {null_recent} of {recent_links} new links have NULL dataset_id!")
                return 1
            else:
                print(f"✅ All {recent_links} new links have proper dataset_id")
        
        # Show dataset distribution of recent links
        if recent_links > 0:
            distribution = db.session.execute(text(
                """
                SELECT 
                    d.label,
                    COUNT(*) as count
                FROM candidate_links cl
                JOIN datasets d ON cl.dataset_id = d.id
                WHERE cl.discovered_at > :cutoff
                GROUP BY d.label
                """
            ), {"cutoff": datetime.utcnow() - timedelta(minutes=5)}).fetchall()
            
            print(f"\n📊 Recent links by dataset:")
            for row in distribution:
                print(f"   {row[0]:45} | {row[1]} links")
        
        print(f"\n{'=' * 80}")
        print("✅ TEST PASSED - Dataset assignment is working correctly!")
        print("=" * 80)
        
        return 0


if __name__ == "__main__":
    exit(main())
