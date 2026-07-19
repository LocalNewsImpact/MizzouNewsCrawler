#!/usr/bin/env python3
"""
Add a discovery section URL to a source.

Usage (run in production pod):
    python add_discovery_section.py <host> <section_url>
    
Example:
    python add_discovery_section.py www.clintondailydemocrat.com https://www.clintondailydemocrat.com/news/
    
The script will:
1. Find the source by hostname
2. Add the URL to the source's discovered_sections JSON field
3. Preserve existing sections
"""

import sys
import json
from datetime import datetime

from src.models.database import DatabaseManager
from sqlalchemy import text


def add_section(host: str, section_url: str) -> str:
    """Add a section URL to a source's discovered_sections."""
    db = DatabaseManager()
    with db.get_session() as s:
        # Find the source
        row = s.execute(
            text("SELECT id, host, discovered_sections FROM sources WHERE host = :host"),
            {"host": host}
        ).fetchone()
        
        if not row:
            return f"ERROR: Source not found: {host}"
        
        source_id, source_host, sections = row
        
        # Initialize sections if empty
        if not sections:
            sections = {
                'urls': [],
                'discovery_method': 'manual',
                'discovered_at': datetime.utcnow().isoformat(),
                'count': 0
            }
        
        # Check if URL already exists
        if section_url in sections.get('urls', []):
            return f"URL already exists: {section_url}"
        
        # Add the new URL
        sections['urls'] = sections.get('urls', []) + [section_url]
        sections['count'] = len(sections['urls'])
        
        # Update the database
        s.execute(
            text("UPDATE sources SET discovered_sections = :sections WHERE id = :sid"),
            {"sid": source_id, "sections": json.dumps(sections)}
        )
        s.commit()
        
        return f"Added {section_url} to {source_host}\nTotal sections: {sections['urls']}"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python add_discovery_section.py <host> <section_url>")
        print("Example: python add_discovery_section.py www.example.com https://www.example.com/news/")
        sys.exit(1)
    
    host = sys.argv[1]
    section_url = sys.argv[2]
    
    result = add_section(host, section_url)
    print(result)
