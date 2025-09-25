#!/usr/bin/env python3
"""
Fix HTML Encoded Authors

This script fixes articles where author names contain HTML entities like
"Emily O&#x27;Leary" and duplicates caused by having both encoded and
decoded versions of the same name.

Usage:
    python fix_html_encoded_authors.py [--dry-run] [--article-id ARTICLE_ID]
"""

import sqlite3
import json
import argparse
import html
from typing import List


def log_info(message: str):
    """Simple logging function"""
    print(f"[INFO] {message}")


def log_error(message: str):
    """Simple error logging function"""
    print(f"[ERROR] {message}")


def clean_html_encoded_authors(authors: List[str]) -> List[str]:
    """
    Clean a list of authors by:
    1. HTML decoding all names
    2. Removing duplicates (case-insensitive)
    3. Preserving order
    """
    if not authors:
        return []
    
    cleaned_authors = []
    seen = set()
    
    for author in authors:
        if not author:
            continue
            
        # HTML decode the author name
        decoded = html.unescape(str(author))
        
        # Add only if not already seen (case-insensitive)
        if decoded.lower() not in seen:
            cleaned_authors.append(decoded)
            seen.add(decoded.lower())
    
    return cleaned_authors


def find_html_encoded_articles(cursor, specific_article_id=None):
    """Find articles with HTML entities in author fields."""
    if specific_article_id:
        cursor.execute('''
            SELECT id, url, title, author
            FROM articles
            WHERE id = ? AND (
                author LIKE '%&#%'
                OR author LIKE '%&amp;%'
                OR author LIKE '%&lt;%'
                OR author LIKE '%&gt;%'
                OR author LIKE '%&quot;%'
            )
        ''', (specific_article_id,))
    else:
        cursor.execute('''
            SELECT id, url, title, author
            FROM articles
            WHERE author LIKE '%&#%'
               OR author LIKE '%&amp;%'
               OR author LIKE '%&lt;%'
               OR author LIKE '%&gt;%'
               OR author LIKE '%&quot;%'
        ''')

    return cursor.fetchall()


def fix_article_authors(cursor, article_id, current_authors, new_authors,
                        dry_run=False):
    """Fix the authors for a specific article."""
    if dry_run:
        log_info(f"[DRY RUN] Would update article {article_id}")
        log_info(f"  Current: {current_authors}")
        log_info(f"  New: {new_authors}")
        return True

    try:
        new_author_json = json.dumps(new_authors)
        cursor.execute('''
            UPDATE articles
            SET author = ?
            WHERE id = ?
        ''', (new_author_json, article_id))

        log_info(f"✅ Updated article {article_id}")
        log_info(f"  From: {current_authors}")
        log_info(f"  To: {new_authors}")
        return True

    except Exception as e:
        log_error(f"Failed to update article {article_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Fix HTML encoded author names")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be changed without changes")
    parser.add_argument("--article-id", type=str,
                        help="Fix only the specified article ID")

    args = parser.parse_args()

    # Connect to database
    db_path = 'data/mizzou.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Find articles with HTML entities
        problematic_articles = find_html_encoded_articles(
            cursor, args.article_id)

        if not problematic_articles:
            if args.article_id:
                log_info(f"No HTML encoding issues found in article "
                         f"{args.article_id}")
            else:
                log_info("No articles found with HTML encoding issues!")
            return

        log_info(f"Found {len(problematic_articles)} articles with "
                 f"HTML encoding issues")
        print("=" * 60)

        fixed_count = 0

        for article_id, url, title, author_json in problematic_articles:
            print(f"\nArticle: {article_id}")
            print(f"URL: {url}")
            print(f"Title: {title[:60]}...")

            try:
                current_authors = (json.loads(author_json)
                                   if author_json else [])
                print(f"Current authors ({len(current_authors)}): "
                      f"{current_authors}")

                # Clean HTML encoding and remove duplicates
                cleaned_authors = clean_html_encoded_authors(current_authors)
                print(f"Cleaned authors ({len(cleaned_authors)}): "
                      f"{cleaned_authors}")

                # Check if any changes needed
                if cleaned_authors != current_authors:
                    if fix_article_authors(cursor, article_id,
                                           current_authors,
                                           cleaned_authors, args.dry_run):
                        fixed_count += 1
                        if len(cleaned_authors) < len(current_authors):
                            duplicates_removed = (len(current_authors) -
                                                  len(cleaned_authors))
                            print(f"  📝 Removed {duplicates_removed} "
                                  f"duplicate(s)")
                else:
                    print("  ✅ No changes needed")
                
            except Exception as e:
                log_error(f"Error processing article {article_id}: {e}")
        
        if not args.dry_run:
            conn.commit()
            log_info(f"✅ Successfully fixed {fixed_count} articles")
        else:
            log_info(f"[DRY RUN] Would fix {fixed_count} articles")
        
        print("=" * 60)
        
    except Exception as e:
        log_error(f"Database error: {e}")
        conn.rollback()
    
    finally:
        conn.close()


if __name__ == "__main__":
    main()
