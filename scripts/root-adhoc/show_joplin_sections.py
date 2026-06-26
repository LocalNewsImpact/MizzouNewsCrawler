import sys
sys.path.insert(0, '/app')

from src.models.database import DatabaseManager
from sqlalchemy import text
import json

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text("""
        SELECT host, canonical_name, discovered_sections
        FROM sources 
        WHERE host LIKE '%joplinglobe%'
        LIMIT 1
    """)).fetchone()
    
    if result:
        print(f'Host: {result[0]}')
        print(f'Name: {result[1]}')
        print()
        
        if result[2]:
            sections = result[2]
            print('Discovered sections structure:')
            print(f'Type: {type(sections)}')
            print(f'Keys: {list(sections.keys()) if isinstance(sections, dict) else "Not a dict"}')
            print()
            
            if isinstance(sections, dict) and 'urls' in sections:
                urls = sections.get('urls', [])
                print(f'Number of discovered section URLs: {len(urls) if urls else 0}')
                if urls:
                    print('\nDiscovered section URLs:')
                    for url in urls[:20]:  # Show first 20
                        print(f'  - {url}')
                    if len(urls) > 20:
                        print(f'  ... and {len(urls) - 20} more')
            else:
                print('Full sections data:')
                print(json.dumps(sections, indent=2))
