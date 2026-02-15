#!/usr/bin/env python3
from src.models.database import DatabaseManager
from sqlalchemy import text

# Section URLs to add for better local news discovery
section_urls = [
    "https://www.joplinglobe.com/news/",
    "https://www.joplinglobe.com/sports/local_sports/",
    "https://www.joplinglobe.com/news/crime_and_courts/",
    "https://www.joplinglobe.com/news/business/",
    "https://www.joplinglobe.com/news/education/"
]

db = DatabaseManager()
with db.get_session() as session:
    # Get current metadata
    result = session.execute(text("""
        SELECT id, metadata
        FROM sources
        WHERE host LIKE '%joplin%'
    """)).fetchone()
    
    if not result:
        print("Joplin Globe not found")
        exit(1)
    
    source_id = result[0]
    metadata = result[1] or {}
    
    # Add section URLs to metadata (discovery code looks for sections.urls)
    metadata['sections'] = {'urls': section_urls}
    
    # Update source
    import json
    session.execute(text("""
        UPDATE sources
        SET metadata = CAST(:metadata AS jsonb)
        WHERE id = :source_id
    """), {"source_id": source_id, "metadata": json.dumps(metadata)})
    
    session.commit()
    
    print(f"✅ Updated Joplin Globe source with {len(section_urls)} section URLs")
    print("\nSection URLs added:")
    for url in section_urls:
        print(f"  - {url}")
