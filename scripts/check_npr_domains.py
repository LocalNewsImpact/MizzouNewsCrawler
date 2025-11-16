#!/usr/bin/env python3
"""
Check which domain the non-wire articles with NPR names come from.
"""

from sqlalchemy import text
from src.models.database import DatabaseManager


def main():
    db = DatabaseManager()
    
    # Sample NPR names from user's list
    npr_names = [
        'a martínez', 'ailsa chang', 'andrew limbong', 'scott simon',
        'leila fadel', 'steve inskeep', 'mary louise kelly', 'michel martin',
        'ayesha rascoe', 'juana summers', 'sacha pfeiffer', 'domenico montanaro'
    ]
    
    print("Checking domains for non-wire articles with NPR bylines:\n")
    
    with db.get_session() as session:
        for name in npr_names:
            query = text("""
                SELECT url, author, status
                FROM articles
                WHERE status != 'wire'
                AND LOWER(author) LIKE :search_pattern
                LIMIT 10
            """)
            
            result = session.execute(query, {"search_pattern": f'%{name}%'})
            matches = result.fetchall()
            
            if matches:
                print(f"\n'{name.title()}' ({len(matches)} shown):")
                for article in matches:
                    if '://' in article.url:
                        domain = article.url.split('/')[2]
                    else:
                        domain = 'unknown'
                    print(f"  [{article.status}] {domain}")
                    print(f"      {article.author}")


if __name__ == "__main__":
    main()
