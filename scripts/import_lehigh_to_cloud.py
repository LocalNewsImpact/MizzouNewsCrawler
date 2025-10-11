#!/usr/bin/env python3
"""
Import Lehigh Valley source list and URLs directly to Cloud SQL.
This script can be run from a Kubernetes pod with Cloud SQL access.
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import uuid

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.database import DatabaseManager
from src.models import Dataset, Source, CandidateLink
from sqlalchemy import text


def import_lehigh_valley():
    """Import Lehigh Valley dataset and URLs to Cloud SQL."""
    
    db = DatabaseManager()
    
    # Lehigh Valley data
    dataset_data = {
        'id': '3c4db976-e30f-4ba5-8b48-0b1c99902003',
        'slug': 'Penn-State-Lehigh',
        'name': 'Penn State Lehigh Valley News',
        'description': 'News sources from Lehigh Valley, Pennsylvania region'
    }
    
    source_data = {
        'id': 'b9033f21-1110-4be7-aa93-15ff48bce725',
        'name': 'Lehigh Valley News',
        'url': 'https://www.lehighvalleynews.com',
        'address': '123 Main St',
        'city': 'Bethlehem',
        'state': 'Pennsylvania',
        'zip_code': '18015',
        'county': 'Northampton'
    }
    
    # Read URLs from file (created from Excel export)
    urls_file = project_root / 'data' / 'lehigh_urls.txt'
    
    with db.get_session() as session:
        print("🔍 Checking if dataset already exists...")
        
        # Check if dataset exists
        existing_dataset = session.query(Dataset).filter_by(id=dataset_data['id']).first()
        
        if existing_dataset:
            print(f"✅ Dataset '{dataset_data['name']}' already exists")
            dataset = existing_dataset
        else:
            print(f"📦 Creating dataset: {dataset_data['name']}")
            dataset = Dataset(
                id=dataset_data['id'],
                slug=dataset_data['slug'],
                name=dataset_data['name'],
                description=dataset_data['description'],
                created_at=datetime.utcnow()
            )
            session.add(dataset)
            session.flush()
            print(f"✅ Dataset created: {dataset.slug}")
        
        # Check if source exists
        existing_source = session.query(Source).filter_by(id=source_data['id']).first()
        
        if existing_source:
            print(f"✅ Source '{source_data['name']}' already exists")
            source = existing_source
        else:
            print(f"🌐 Creating source: {source_data['name']}")
            source = Source(
                id=source_data['id'],
                name=source_data['name'],
                url=source_data['url'],
                address=source_data['address'],
                city=source_data['city'],
                state=source_data['state'],
                zip_code=source_data['zip_code'],
                county=source_data['county'],
                created_at=datetime.utcnow()
            )
            session.add(source)
            session.flush()
            print(f"✅ Source created: {source.name}")
        
        # Import URLs
        if not urls_file.exists():
            print(f"❌ URLs file not found: {urls_file}")
            print("\nYou need to export URLs from local database first:")
            print("  Run this locally:")
            print("  python3 -c \"from src.models.database import DatabaseManager; from sqlalchemy import text;")
            print("    db = DatabaseManager();")
            print("    with db.get_session() as session:")
            print("      urls = session.execute(text(")
            print("        'SELECT url FROM candidate_links WHERE dataset_id = \\'3c4db976-e30f-4ba5-8b48-0b1c99902003\\''))")
            print("      with open('data/lehigh_urls.txt', 'w') as f:")
            print("        for row in urls: f.write(row[0] + '\\\\n')\"")
            return
        
        print(f"\n📄 Reading URLs from {urls_file}")
        with open(urls_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        print(f"📥 Found {len(urls)} URLs to import")
        
        # Check for existing URLs
        existing_count = session.query(CandidateLink).filter(
            CandidateLink.dataset_id == dataset.id
        ).count()
        
        if existing_count > 0:
            print(f"⚠️  Found {existing_count} existing URLs for this dataset")
            response = input("Delete existing URLs and re-import? (yes/no): ")
            if response.lower() == 'yes':
                deleted = session.query(CandidateLink).filter(
                    CandidateLink.dataset_id == dataset.id
                ).delete()
                session.commit()
                print(f"🗑️  Deleted {deleted} existing URLs")
            else:
                print("Skipping import")
                return
        
        # Import URLs
        print("\n💾 Importing URLs...")
        imported = 0
        skipped = 0
        
        for i, url in enumerate(urls, 1):
            # Check if URL already exists
            existing = session.query(CandidateLink).filter_by(url=url).first()
            
            if existing:
                skipped += 1
                continue
            
            # Create candidate link
            candidate = CandidateLink(
                id=str(uuid.uuid4()),
                url=url,
                source_id=source.id,
                dataset_id=dataset.id,
                status='article',  # Ready for extraction
                discovered_at=datetime.utcnow()
            )
            session.add(candidate)
            imported += 1
            
            # Commit in batches
            if i % 100 == 0:
                session.commit()
                print(f"  ✓ Imported {imported}/{len(urls)} URLs...")
        
        session.commit()
        
        print(f"\n✅ Import complete!")
        print(f"   Imported: {imported}")
        print(f"   Skipped (duplicates): {skipped}")
        print(f"   Total: {len(urls)}")
        
        # Verify
        total_count = session.query(CandidateLink).filter(
            CandidateLink.dataset_id == dataset.id,
            CandidateLink.status == 'article'
        ).count()
        
        print(f"\n🔍 Verification: {total_count} URLs ready for extraction")


if __name__ == '__main__':
    print("=" * 60)
    print("Lehigh Valley Cloud SQL Import")
    print("=" * 60)
    print()
    
    import_lehigh_valley()
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)
