#!/usr/bin/env python3
"""
Rename publinks-publinks_csv dataset to Mizzou-Missouri-State.

This script updates:
1. datasets.slug: publinks-publinks_csv → Mizzou-Missouri-State
2. datasets.label: Publisher Links from publinks.csv → Mizzou Missouri State
3. datasets.name: Updated for clarity
4. datasets.description: Updated description
"""

from src.models.database import DatabaseManager
from sqlalchemy import text


def main():
    print("=" * 80)
    print("RENAMING DATASET: publinks-publinks_csv → Mizzou-Missouri-State")
    print("=" * 80)
    
    with DatabaseManager() as db:
        # Get current dataset info
        result = db.session.execute(text("""
            SELECT 
                id,
                slug,
                label,
                name,
                description,
                cron_enabled
            FROM datasets
            WHERE slug = 'publinks-publinks_csv'
        """)).fetchone()
        
        if not result:
            print("❌ Dataset 'publinks-publinks_csv' not found!")
            return 1
        
        dataset_id = result[0]
        
        print("\n=== Current Dataset Info ===")
        print(f"ID: {dataset_id}")
        print(f"Slug: {result[1]}")
        print(f"Label: {result[2]}")
        print(f"Name: {result[3]}")
        print(f"Description: {result[4]}")
        print(f"Cron Enabled: {result[5]}")
        
        # Count related records
        links_count = db.session.execute(text("""
            SELECT COUNT(*) FROM candidate_links WHERE dataset_id = :id
        """), {"id": dataset_id}).scalar()
        
        sources_count = db.session.execute(text("""
            SELECT COUNT(*) FROM dataset_sources WHERE dataset_id = :id
        """), {"id": dataset_id}).scalar()
        
        print(f"\n=== Related Records ===")
        print(f"Candidate Links: {links_count:,}")
        print(f"Sources: {sources_count}")
        
        # New values
        new_slug = "Mizzou-Missouri-State"
        new_label = "Mizzou Missouri State"
        new_name = "Missouri State News Sources"
        new_description = (
            "Primary dataset for Missouri state news sources. "
            "Includes local newspapers, radio, and TV stations across Missouri counties."
        )
        
        print("\n=== New Dataset Info ===")
        print(f"Slug: {new_slug}")
        print(f"Label: {new_label}")
        print(f"Name: {new_name}")
        print(f"Description: {new_description}")
        
        # Confirm
        print(f"\n⚠️  This will update the dataset record.")
        print(f"   {links_count:,} candidate_links and {sources_count} sources ")
        print(f"   will remain associated via UUID (no changes needed).")
        
        response = input("\nProceed with rename? (yes/no): ").strip().lower()
        
        if response != "yes":
            print("❌ Aborted by user")
            return 0
        
        # Perform the update
        print("\n🔄 Updating dataset record...")
        db.session.execute(text("""
            UPDATE datasets
            SET 
                slug = :new_slug,
                label = :new_label,
                name = :new_name,
                description = :new_description
            WHERE id = :id
        """), {
            "id": dataset_id,
            "new_slug": new_slug,
            "new_label": new_label,
            "new_name": new_name,
            "new_description": new_description,
        })
        
        db.session.commit()
        
        print("✅ Dataset updated successfully")
        
        # Verify the update
        verify = db.session.execute(text("""
            SELECT slug, label, name, description
            FROM datasets
            WHERE id = :id
        """), {"id": dataset_id}).fetchone()
        
        print("\n=== Verified New Values ===")
        print(f"Slug: {verify[0]}")
        print(f"Label: {verify[1]}")
        print(f"Name: {verify[2]}")
        print(f"Description: {verify[3]}")
        
        # Check that relationships are intact
        print(f"\n=== Verifying Relationships ===")
        
        links_after = db.session.execute(text("""
            SELECT COUNT(*) FROM candidate_links WHERE dataset_id = :id
        """), {"id": dataset_id}).scalar()
        
        sources_after = db.session.execute(text("""
            SELECT COUNT(*) FROM dataset_sources WHERE dataset_id = :id
        """), {"id": dataset_id}).scalar()
        
        print(f"Candidate Links: {links_after:,} (unchanged: {links_after == links_count})")
        print(f"Sources: {sources_after} (unchanged: {sources_after == sources_count})")
        
        if links_after != links_count or sources_after != sources_count:
            print("\n⚠️  WARNING: Relationship counts changed!")
            return 1
        
        print("\n" + "=" * 80)
        print("✅ DATASET RENAME COMPLETE")
        print("=" * 80)
        
        print("\n📋 Next Steps:")
        print("1. Update Dockerfile.crawler CMD to use new label:")
        print('   --dataset "Mizzou Missouri State"')
        print("\n2. Update any scripts/jobs that reference the old slug/label")
        print("\n3. Rebuild and deploy crawler image")
        
        return 0


if __name__ == "__main__":
    exit(main())
