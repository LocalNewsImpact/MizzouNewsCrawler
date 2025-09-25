#!/usr/bin/env python3
"""
Script to clean and normalize author column in articles table using BylineCleaner.
"""

import sqlite3
import sys
import os
from typing import Dict, Any

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def get_database_connection(db_path: str) -> sqlite3.Connection:
    """Get database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def clean_authors_in_database(db_path: str, dry_run: bool = True) -> Dict[str, Any]:
    """Clean all author entries in the articles table."""
    cleaner = BylineCleaner()
    conn = get_database_connection(db_path)
    
    stats = {
        'total_articles': 0,
        'articles_with_authors': 0,
        'cleaned_count': 0,
        'unchanged_count': 0,
        'wire_services_count': 0,
        'empty_results_count': 0,
        'changes': []
    }
    
    try:
        # Get all articles with authors
        cursor = conn.execute("""
            SELECT id, author 
            FROM articles 
            WHERE author IS NOT NULL AND author != ''
            ORDER BY id
        """)
        
        articles = cursor.fetchall()
        stats['total_articles'] = len(articles)
        stats['articles_with_authors'] = len(articles)
        
        print(f"Found {len(articles)} articles with author data")
        print("=" * 60)
        
        for article in articles:
            article_id = article['id']
            original_author = article['author']
            
            # Clean the author using byline cleaner
            cleaned_authors = cleaner.clean_byline(original_author)
            
            # Convert list to JSON string for storage
            if isinstance(cleaned_authors, list):
                if len(cleaned_authors) == 0:
                    # Empty result - likely titles only
                    new_author_value = None
                    stats['empty_results_count'] += 1
                    status = "REMOVED (titles only)"
                elif len(cleaned_authors) == 1 and cleaned_authors[0] == original_author.strip():
                    # No change needed
                    new_author_value = original_author
                    stats['unchanged_count'] += 1
                    continue  # Skip logging unchanged entries
                else:
                    # Join multiple authors with comma separation
                    new_author_value = ', '.join(cleaned_authors)
                    
                    # Check if this is a wire service
                    if any(ws.lower() in new_author_value.lower() 
                           for ws in ['associated press', 'reuters', 'ap', 'bloomberg']):
                        stats['wire_services_count'] += 1
                        status = "WIRE SERVICE"
                    else:
                        stats['cleaned_count'] += 1
                        status = "CLEANED"
            else:
                # Unexpected result type
                new_author_value = str(cleaned_authors)
                stats['cleaned_count'] += 1
                status = "CONVERTED"
            
            # Log the change
            change_info = {
                'id': article_id,
                'original': original_author,
                'cleaned': new_author_value,
                'status': status
            }
            stats['changes'].append(change_info)
            
            print(f"ID: {article_id[:8]}...")
            print(f"  Original: {original_author}")
            print(f"  Cleaned:  {new_author_value}")
            print(f"  Status:   {status}")
            print("-" * 40)
            
            # Update database if not dry run
            if not dry_run:
                conn.execute("""
                    UPDATE articles 
                    SET author = ?, processed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_author_value, article_id))
        
        if not dry_run:
            conn.commit()
            print("\n✅ Database updated successfully!")
        else:
            print("\n🔍 DRY RUN - No changes made to database")
            
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error: {e}")
        raise
    finally:
        conn.close()
    
    return stats


def print_summary(stats: Dict[str, Any]) -> None:
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("AUTHOR CLEANING SUMMARY")
    print("=" * 60)
    print(f"Total articles examined:     {stats['total_articles']}")
    print(f"Articles with authors:       {stats['articles_with_authors']}")
    print(f"Authors cleaned:             {stats['cleaned_count']}")
    print(f"Authors unchanged:           {stats['unchanged_count']}")
    print(f"Wire service entries:        {stats['wire_services_count']}")
    print(f"Empty results (removed):     {stats['empty_results_count']}")
    print(f"Total changes made:          {len(stats['changes'])}")
    
    if stats['changes']:
        print("\nFirst 5 changes:")
        for i, change in enumerate(stats['changes'][:5]):
            print(f"  {i+1}. {change['original']} → {change['cleaned']} ({change['status']})")


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean author column in articles table')
    parser.add_argument('--db', default='data/mizzou.db', help='Database path')
    parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry run)')
    
    args = parser.parse_args()
    
    db_path = args.db
    dry_run = not args.apply
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        sys.exit(1)
    
    print(f"Cleaning authors in database: {db_path}")
    print(f"Mode: {'APPLY CHANGES' if not dry_run else 'DRY RUN'}")
    print()
    
    try:
        stats = clean_authors_in_database(db_path, dry_run=dry_run)
        print_summary(stats)
        
        if dry_run and stats['changes']:
            print(f"\nTo apply changes, run: python {__file__} --apply")
            
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()