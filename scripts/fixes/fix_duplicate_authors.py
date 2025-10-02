#!/usr/bin/env python3
"""
Script to fix the remaining duplicate author entries.
"""

import os
import sqlite3
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.byline_cleaner import BylineCleaner


def fix_duplicate_authors(db_path: str, dry_run: bool = True):
    """Fix any remaining duplicate author entries."""
    cleaner = BylineCleaner()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Find articles with duplicate names in author field
        cursor = conn.execute("""
            SELECT id, author 
            FROM articles 
            WHERE author IS NOT NULL 
            AND author LIKE '%,%' 
            AND author != 'Isabella Volmert, Obed Lamy'
        """)

        articles = cursor.fetchall()
        print(f"Found {len(articles)} articles with potential duplicates")

        for article in articles:
            article_id = article['id']
            original_author = article['author']

            # Re-clean to fix duplicates
            cleaned_authors = cleaner.clean_byline(original_author)

            if isinstance(cleaned_authors, list) and len(cleaned_authors) > 0:
                # Apply manual deduplication while preserving order
                seen = set()
                deduplicated = []
                for author in cleaned_authors:
                    author_lower = author.lower().strip()
                    if author_lower not in seen:
                        seen.add(author_lower)
                        deduplicated.append(author)

                new_author_value = ', '.join(deduplicated)

                if new_author_value != original_author:
                    print(f"ID: {article_id[:8]}...")
                    print(f"  Original: {original_author}")
                    print(f"  Fixed:    {new_author_value}")
                    print("-" * 40)

                    if not dry_run:
                        conn.execute("""
                            UPDATE articles 
                            SET author = ?, processed_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (new_author_value, article_id))

        if not dry_run:
            conn.commit()
            print("✅ Duplicates fixed!")
        else:
            print("🔍 DRY RUN - No changes made")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        conn.close()


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description='Fix duplicate author entries')
    parser.add_argument('--db', default='data/mizzou.db', help='Database path')
    parser.add_argument('--apply', action='store_true', help='Apply changes')

    args = parser.parse_args()

    fix_duplicate_authors(args.db, dry_run=not args.apply)


if __name__ == "__main__":
    main()
