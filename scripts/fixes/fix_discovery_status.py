#!/usr/bin/env python3

# Fix discovery_status function in quick_query.py to use discovery_attempted column

def fix_discovery_status():
    with open('scripts/quick_query.py') as f:
        content = f.read()

    # Find and replace the old discovery_status function
    old_function = '''def discovery_status():
    """Check overall discovery status across all sources."""
    queries = [
        ("SELECT COUNT(*) as total_sources FROM sources", None, "Total Sources"),
        ("""
            SELECT COUNT(DISTINCT s.id) as sources_with_discoveries
            FROM sources s
            JOIN candidate_links cl ON s.id = cl.source_host_id
        """, None, "Sources With Discovery Attempts"),
        ("""
            SELECT COUNT(*) as unattempted_sources
            FROM sources s
            LEFT JOIN candidate_links cl ON s.id = cl.source_host_id
            WHERE cl.source_host_id IS NULL
        """, None, "Sources Never Attempted"),
    ]
    
    for query, params, desc in queries:
        execute_query(query, params, desc)'''

    new_function = '''def discovery_status():
    """Check overall discovery status across all sources."""
    queries = [
        ("SELECT COUNT(*) as total_sources FROM sources", None, "Total Sources"),
        ("""
            SELECT COUNT(*) as sources_with_discoveries
            FROM sources
            WHERE discovery_attempted IS NOT NULL
        """, None, "Sources With Discovery Attempts"),
        ("""
            SELECT COUNT(*) as unattempted_sources
            FROM sources
            WHERE discovery_attempted IS NULL
        """, None, "Sources Never Attempted"),
    ]
    
    for query, params, desc in queries:
        execute_query(query, params, desc)'''

    content = content.replace(old_function, new_function)

    with open('scripts/quick_query.py', 'w') as f:
        f.write(content)

    print("Updated discovery_status function to use discovery_attempted column")

if __name__ == "__main__":
    fix_discovery_status()
