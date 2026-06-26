#!/usr/bin/env python3
from src.models.database import DatabaseManager
from sqlalchemy import text
import json

# Section URLs by site
sections_by_site = {
    "bolivarmonews.com": [
        "https://bolivarmonews.com/business/",
        "https://bolivarmonews.com/community/",
        "https://bolivarmonews.com/crime/",
        "https://bolivarmonews.com/lifestyles/",
        "https://bolivarmonews.com/news/",
        "https://bolivarmonews.com/sports/",
        "https://bolivarmonews.com/opinion/",
    ],
    "mycameronnews.com": [
        "https://mycameronnews.com/premium/agriculture-news/",
        "https://mycameronnews.com/premium/business-news/",
        "https://mycameronnews.com/premium/education-careers/",
        "https://mycameronnews.com/premium/entertainment-news/",
        "https://mycameronnews.com/news/",
        "https://mycameronnews.com/sports/",
    ],
    "thegriffonnews.com": [
        "https://thegriffonnews.com/news/",
        "https://thegriffonnews.com/news/local/",
        "https://thegriffonnews.com/sports/",
    ],
    "www.boonvilledailynews.com": [
        "https://www.boonvilledailynews.com/category/community/",
        "https://www.boonvilledailynews.com/category/news/",
        "https://www.boonvilledailynews.com/category/opinion/",
        "https://www.boonvilledailynews.com/category/sports/",
    ],
    "www.bransontrilakesnews.com": [
        "https://www.bransontrilakesnews.com/entertainment/",
        "https://www.bransontrilakesnews.com/sports/",
    ],
    "www.douglascountyherald.com": [
        "https://www.douglascountyherald.com/category/school-news/sports-school-news/",
    ],
    "www.richmond-dailynews.com": [
        "https://www.richmond-dailynews.com/news/",
        "https://www.richmond-dailynews.com/sports/",
    ],
    "www.webstercountycitizen.com": [
        "https://www.webstercountycitizen.com/news/",
    ],
}

db = DatabaseManager()

print("="*80)
print("ADDING SECTION URLs TO SOURCES")
print("="*80)

with db.get_session() as session:
    for site, urls in sections_by_site.items():
        # Find source
        source = session.execute(text("""
            SELECT id, host, canonical_name, metadata
            FROM sources
            WHERE host LIKE :pattern
            LIMIT 1
        """), {"pattern": f"%{site}%"}).fetchone()
        
        if not source:
            print(f"\n❌ {site}: NOT FOUND")
            continue
        
        source_id = source[0]
        metadata = source[3] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        # Add sections
        metadata['sections'] = {'urls': urls}
        
        # Update database
        session.execute(text("""
            UPDATE sources
            SET metadata = CAST(:metadata AS jsonb)
            WHERE id = :source_id
        """), {"source_id": source_id, "metadata": json.dumps(metadata)})
        
        print(f"\n✅ {source[1]} ({source[2]})")
        print(f"   Added {len(urls)} section URLs:")
        for url in urls:
            print(f"      - {url}")
    
    session.commit()

print("\n" + "="*80)
print(f"✅ Updated {len(sections_by_site)} sources with section URLs")
print("="*80)
