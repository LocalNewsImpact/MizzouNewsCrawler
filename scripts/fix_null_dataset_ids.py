#!/usr/bin/env python3
"""
Fix NULL dataset_id values in candidate_links table.

This script assigns the correct dataset_id to candidate_links that have NULL dataset_id
by matching their source_id against the dataset_sources junction table.

Background:
- The discovery pipeline was running without --dataset parameter
- This caused candidate_links to be created with NULL dataset_id
- 6,174 candidate_links currently have NULL dataset_id
- These should be assigned to "Publisher Links from publinks.csv" dataset
"""

from src.models.database import DatabaseManager
from sqlalchemy import text


def main():
    print("=" * 80)
    print("FIXING NULL DATASET_IDs IN CANDIDATE_LINKS")
    print("=" * 80)
    
    with DatabaseManager() as db:
        # First, get the Mizzou Missouri State dataset UUID
        result = db.session.execute(text("""
            SELECT id, label, slug
            FROM datasets
            WHERE slug = 'Mizzou-Missouri-State'
        """)).fetchone()
        
        if not result:
            print("❌ ERROR: Could not find 'Mizzou-Missouri-State' dataset!")
            return 1
        
        mizzou_dataset_id = result[0]
        print(f"\n✓ Found dataset: {result[1]}")
        print(f"  UUID: {mizzou_dataset_id}")
        print(f"  Slug: {result[2]}")
        
        # Count NULL records before fix
        null_count = db.session.execute(text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE dataset_id IS NULL
        """)).scalar()
        
        print(f"\n📊 Current state:")
        print(f"  Candidate links with NULL dataset_id: {null_count:,}")
        
        # Check how many can be matched via dataset_sources
        matchable = db.session.execute(text("""
            SELECT COUNT(DISTINCT cl.id)
            FROM candidate_links cl
            JOIN dataset_sources ds ON cl.source_id = ds.source_id
            WHERE cl.dataset_id IS NULL
              AND ds.dataset_id = :dataset_id
        """), {"dataset_id": mizzou_dataset_id}).scalar()
        
        print(f"  Links matchable via dataset_sources: {matchable:,}")
        
        if matchable == 0:
            print("\n⚠️  No candidate_links can be matched via dataset_sources!")
            print("   This may indicate the sources aren't properly linked to the dataset.")
            return 1
        
        # Show sample of what will be updated
        print(f"\n📋 Sample of links to be updated:")
        samples = db.session.execute(text("""
            SELECT 
                cl.url,
                s.host,
                s.canonical_name,
                s.county
            FROM candidate_links cl
            JOIN sources s ON cl.source_id = s.id
            JOIN dataset_sources ds ON cl.source_id = ds.source_id
            WHERE cl.dataset_id IS NULL
              AND ds.dataset_id = :dataset_id
            LIMIT 5
        """), {"dataset_id": mizzou_dataset_id}).fetchall()
        
        for row in samples:
            print(f"  • {row[1]:30} | {row[2] or 'N/A':30} | {row[3] or 'N/A'}")
        
        # Ask for confirmation
        print(f"\n⚠️  About to update {matchable:,} candidate_links")
        print(f"   Setting dataset_id to: {mizzou_dataset_id}")
        response = input("\nProceed with update? (yes/no): ").strip().lower()
        
        if response != "yes":
            print("❌ Aborted by user")
            return 0
        
        # Perform the update
        print("\n🔄 Updating records...")
        result = db.session.execute(text("""
            UPDATE candidate_links
            SET dataset_id = :dataset_id
            WHERE id IN (
                SELECT cl.id
                FROM candidate_links cl
                JOIN dataset_sources ds ON cl.source_id = ds.source_id
                WHERE cl.dataset_id IS NULL
                  AND ds.dataset_id = :dataset_id
            )
        """), {"dataset_id": mizzou_dataset_id})
        
        db.session.commit()
        updated_count = result.rowcount
        
        print(f"✅ Updated {updated_count:,} candidate_links")
        
        # Verify the fix
        remaining_null = db.session.execute(text("""
            SELECT COUNT(*)
            FROM candidate_links
            WHERE dataset_id IS NULL
        """)).scalar()
        
        print(f"\n📊 After update:")
        print(f"  Remaining NULL dataset_id: {remaining_null:,}")
        
        # Show dataset distribution
        print(f"\n📊 Dataset distribution:")
        distribution = db.session.execute(text("""
            SELECT 
                COALESCE(d.label, 'NULL') as dataset_name,
                COUNT(*) as count
            FROM candidate_links cl
            LEFT JOIN datasets d ON cl.dataset_id = d.id
            GROUP BY d.label
            ORDER BY count DESC
        """)).fetchall()
        
        for row in distribution:
            print(f"  {row[0]:40} | {row[1]:,} links")
        
        print("\n✅ Dataset ID fix complete!")
        
        if remaining_null > 0:
            print(f"\n⚠️  {remaining_null:,} candidate_links still have NULL dataset_id")
            print("   These may be from sources not assigned to any dataset.")
            print("   Run this query to investigate:")
            print("   SELECT DISTINCT s.host, s.canonical_name FROM candidate_links cl")
            print("   JOIN sources s ON cl.source_id = s.id")
            print("   WHERE cl.dataset_id IS NULL LIMIT 10;")
        
        return 0


if __name__ == "__main__":
    exit(main())
