#!/usr/bin/env python3
from src.models.database import DatabaseManager
from sqlalchemy import text
import json

db = DatabaseManager()

# Section URLs for Warrensburg Star Journal local news
section_urls = [
    "https://www.warrensburgstarjournal.com/news/",
    "https://www.warrensburgstarjournal.com/sports/",
    "https://www.warrensburgstarjournal.com/community/",
]

with db.get_session() as session:
    # Find the source
    source = session.execute(text("""
        SELECT id, host, metadata
        FROM sources
        WHERE host LIKE '%warrensburg%'
    """)).fetchone()
    
    if not source:
        print("❌ Source not found")
        exit(1)
        
    source_id = source[0]
    metadata = source[2] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    
    # Update metadata with section URLs
    metadata['sections'] = {'urls': section_urls}
    
    # Unpause the source and add section URLs
    session.execute(text("""
        UPDATE sources
        SET status = 'active',
            metadata = CAST(:metadata AS jsonb),
            no_effective_methods_consecutive = 0,
            no_effective_methods_last_seen = NULL
        WHERE id = :source_id
    """), {"source_id": source_id, "metadata": json.dumps(metadata)})
    
    session.commit()
    
    print("✅ Updated Warrensburg Star Journal:")
    print("   - Status changed: paused → active")
    print("   - Reset failure counters to 0")
    print(f"   - Added {len(section_urls)} section URLs:")
    for url in section_urls:
        print(f"     - {url}")
    print("\n📋 Next discovery run will:")
    print("   1. Skip RSS/sitemap (known to return 403)")
    print("   2. Use section URLs for direct crawling")
    print("   3. newspaper4k will crawl each section page for article links")
