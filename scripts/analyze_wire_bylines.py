#!/usr/bin/env python3
"""
Analyze bylines in wire articles to find how many other articles contain
the same individual author names.
"""

import re
from collections import defaultdict
from sqlalchemy import text
from src.models.database import DatabaseManager


def extract_author_names(byline):
    """
    Extract individual author names from a byline.
    
    Handles formats like:
    - "John Smith"
    - "John Smith, Jane Doe"
    - "John Smith and Jane Doe"
    - "John Smith, Jane Doe and Bob Johnson"
    - "JOHN SMITH, JANE DOE, Associated Press"
    """
    if not byline:
        return []
    
    # Remove wire service names at the end
    wire_services = [
        'associated press', 'reuters', 'usa today', 'cnn',
        'afp', 'states newsroom', 'stacker', 'the conversation',
        'tribune news service', 'mcclatchy', 'ap'
    ]
    
    byline_lower = byline.lower().strip()
    for service in wire_services:
        # Remove service name if at end (possibly preceded by comma/and)
        pattern = rf',?\s*(and\s+)?{re.escape(service)}$'
        byline_lower = re.sub(pattern, '', byline_lower, flags=re.IGNORECASE)
    
    # Remove "By " prefix
    byline_lower = re.sub(r'^by\s+', '', byline_lower, flags=re.IGNORECASE)
    
    # Split on common delimiters
    # Replace " and " with ", " for uniform splitting
    byline_lower = re.sub(r'\s+and\s+', ', ', byline_lower)
    
    # Split on comma
    names = [name.strip() for name in byline_lower.split(',')]
    
    # Filter out empty strings and wire service remnants
    valid_names = []
    for name in names:
        name = name.strip()
        if name and len(name) > 2 and name not in wire_services:
            valid_names.append(name)
    
    return valid_names


def main():
    db = DatabaseManager()
    
    print("Analyzing wire article bylines in production...\n")
    
    with db.get_session() as session:
        # Get all wire articles with bylines
        query = text("""
            SELECT id, author, url, title
            FROM articles
            WHERE status = 'wire'
            AND author IS NOT NULL
            AND author != ''
            ORDER BY author
        """)
        
        result = session.execute(query)
        wire_articles = result.fetchall()
        
        print(f"Found {len(wire_articles)} wire articles with bylines\n")
        
        # Extract all unique author names from wire articles
        author_names = set()
        wire_bylines = {}
        
        for article in wire_articles:
            names = extract_author_names(article.author)
            wire_bylines[article.id] = (article.author, names)
            author_names.update(names)
        
        print(f"Extracted {len(author_names)} unique author names from wire articles\n")
        
        if not author_names:
            print("No author names found in wire articles")
            return
        
        # Now search for these names in non-wire articles
        print("Searching for these author names in non-wire articles...\n")
        
        # Track which names appear in non-wire articles
        name_occurrences = defaultdict(list)
        
        for name in sorted(author_names):
            # Search for articles containing this name in the byline
            search_query = text("""
                SELECT id, author, url, title, status
                FROM articles
                WHERE status != 'wire'
                AND author IS NOT NULL
                AND LOWER(author) LIKE :search_pattern
                LIMIT 100
            """)
            
            search_pattern = f'%{name}%'
            result = session.execute(search_query, {"search_pattern": search_pattern})
            matches = result.fetchall()
            
            if matches:
                name_occurrences[name] = matches
                print(f"'{name}': {len(matches)} non-wire articles")
        
        # Generate summary report
        print("\n" + "="*80)
        print("SUMMARY REPORT")
        print("="*80)
        
        total_names_with_matches = len(name_occurrences)
        total_names = len(author_names)
        
        print(f"\nTotal unique author names in wire articles: {total_names}")
        print(f"Names appearing in non-wire articles: {total_names_with_matches}")
        print(f"Names NOT appearing in non-wire articles: {total_names - total_names_with_matches}")
        
        if name_occurrences:
            print("\n" + "-"*80)
            print("DETAILED BREAKDOWN (Top 20 names by occurrence)")
            print("-"*80)
            
            # Sort by number of occurrences
            sorted_names = sorted(
                name_occurrences.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:20]
            
            for name, articles in sorted_names:
                print(f"\n'{name.title()}': {len(articles)} non-wire articles")
                
                # Show first 3 examples
                for i, article in enumerate(articles[:3], 1):
                    print(f"  {i}. [{article.status}] {article.author}")
                    print(f"     {article.url}")
                
                if len(articles) > 3:
                    print(f"  ... and {len(articles) - 3} more")
        
        # Export full results to CSV
        csv_path = '/tmp/wire_byline_analysis.csv'
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write("author_name,non_wire_count,example_bylines,example_urls\n")
            
            for name in sorted(author_names):
                matches = name_occurrences.get(name, [])
                count = len(matches)
                
                if matches:
                    example_bylines = " | ".join([m.author for m in matches[:3]])
                    example_urls = " | ".join([m.url for m in matches[:3]])
                else:
                    example_bylines = ""
                    example_urls = ""
                
                # Escape commas in CSV
                example_bylines = example_bylines.replace('"', '""')
                example_urls = example_urls.replace('"', '""')
                
                f.write(f'"{name}",{count},"{example_bylines}","{example_urls}"\n')
        
        print(f"\n\n✓ Full results exported to: {csv_path}")


if __name__ == "__main__":
    main()
