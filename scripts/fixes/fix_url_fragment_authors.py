#!/usr/bin/env python3
"""
Fix URL Fragment Authors

This script identifies and fixes articles where URL fragments were incorrectly
identified as author names (like "Www..Com"). It uses the improved byline cleaner
to re-process the authors and remove URL fragments.

Usage:
    python fix_url_fragment_authors.py [--dry-run] [--article-id ARTICLE_ID]
"""

import argparse
import json
import sqlite3

# Import our improved byline cleaner
from src.utils.byline_cleaner import BylineCleaner


def log_info(message: str):
    """Simple logging function"""
    print(f"[INFO] {message}")


def log_error(message: str):
    """Simple error logging function"""
    print(f"[ERROR] {message}")


def find_articles_with_url_fragments(db_path: str) -> list[tuple]:
    """
    Find articles where author field contains URL fragments.

    Returns:
        List of tuples: (article_id, url, title, current_authors, problematic_authors)
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get all articles with author data
        query = """
        SELECT id, url, title, author
        FROM articles 
        WHERE author IS NOT NULL 
        AND author != '[]'
        AND author != ''
        """

        cursor.execute(query)
        results = cursor.fetchall()

    finally:
        conn.close()

    # Check each article for URL fragments
    problematic_articles = []
    cleaner = BylineCleaner(enable_telemetry=False)

    for article_id, url, title, author_json in results:
        try:
            # Parse author JSON
            authors = json.loads(author_json)
            if not isinstance(authors, list):
                continue

            # Check each author for URL fragments
            url_fragments = []
            for author in authors:
                if cleaner._is_url_fragment(author):
                    url_fragments.append(author)

            # If we found URL fragments, add to problematic list
            if url_fragments:
                problematic_articles.append(
                    (article_id, url, title, authors, url_fragments)
                )

        except (json.JSONDecodeError, TypeError):
            # Skip articles with invalid JSON
            continue

    log_info(
        f"Found {len(problematic_articles)} articles with URL fragments in authors"
    )
    return problematic_articles


def fix_article_authors(
    article_data: list[tuple], db_path: str, dry_run: bool = True
) -> dict:
    """
    Fix articles by removing URL fragments from author fields.

    Args:
        article_data: List of problematic articles
        db_path: Path to database
        dry_run: If True, only show what would be changed

    Returns:
        Dictionary with statistics
    """
    stats = {"total_processed": 0, "fixed": 0, "unchanged": 0, "errors": 0}

    cleaner = BylineCleaner(enable_telemetry=False)

    if not dry_run:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

    try:
        for article_id, url, title, current_authors, url_fragments in article_data:
            stats["total_processed"] += 1

            # Filter out URL fragments
            clean_authors = [
                author
                for author in current_authors
                if not cleaner._is_url_fragment(author)
            ]

            print(f"\\nArticle: {article_id}")
            print(f"  URL: {url}")
            print(f"  Title: {title[:60]}...")
            print(f"  Current authors: {current_authors}")
            print(f"  URL fragments found: {url_fragments}")
            print(f"  Fixed authors: {clean_authors}")

            # Check if there's actually a change
            if clean_authors == current_authors:
                print("  Status: ➡️ No change needed")
                stats["unchanged"] += 1
                continue

            if not dry_run:
                try:
                    # Update the database
                    new_author_json = json.dumps(clean_authors)
                    cursor.execute(
                        "UPDATE articles SET author = ? WHERE id = ?",
                        (new_author_json, article_id),
                    )
                    print("  Status: ✅ Fixed in database")
                    stats["fixed"] += 1

                except Exception as e:
                    print(f"  Status: ❌ Database update failed: {e}")
                    stats["errors"] += 1
            else:
                print("  Status: 🔍 Would fix (dry run)")
                stats["fixed"] += 1

        if not dry_run:
            conn.commit()

    finally:
        if not dry_run:
            conn.close()

    return stats


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Fix URL fragment authors")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )
    parser.add_argument("--article-id", type=str, help="Fix specific article ID only")
    parser.add_argument(
        "--db-path", type=str, default="data/mizzou.db", help="Path to database file"
    )

    args = parser.parse_args()

    print("🔧 URL FRAGMENT AUTHOR FIXER")
    print("=" * 50)

    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
    else:
        print("🚀 LIVE MODE - Changes will be applied to database")

    print()

    # Find problematic articles
    log_info("Scanning articles for URL fragments in author fields...")
    problematic_articles = find_articles_with_url_fragments(args.db_path)

    if not problematic_articles:
        print("✅ No articles found with URL fragment authors!")
        return

    # Filter for specific article if requested
    if args.article_id:
        problematic_articles = [
            article for article in problematic_articles if article[0] == args.article_id
        ]

        if not problematic_articles:
            print(
                f"❌ Article {args.article_id} not found or doesn't have URL fragment issues"
            )
            return

        print(f"🎯 Focusing on specific article: {args.article_id}")

    print(
        f"\\n🚨 Found {len(problematic_articles)} articles with URL fragment authors:"
    )

    # Show summary of issues
    for i, (article_id, url, title, authors, fragments) in enumerate(
        problematic_articles, 1
    ):
        print(f"{i}. {article_id}: {fragments} in {authors}")

    print()

    # Ask for confirmation if not dry run
    if not args.dry_run:
        response = input("Do you want to fix these articles? (y/N): ")
        if response.lower() not in ["y", "yes"]:
            print("❌ Cancelled by user")
            return

    # Fix the articles
    stats = fix_article_authors(problematic_articles, args.db_path, args.dry_run)

    print()
    print("=" * 50)
    print("📊 SUMMARY:")
    print(f"   Total processed: {stats['total_processed']}")
    print(f"   ✅ Fixed: {stats['fixed']}")
    print(f"   ➡️ Unchanged: {stats['unchanged']}")
    print(f"   ❌ Errors: {stats['errors']}")

    if args.dry_run:
        print("\\n🔍 This was a dry run. Use --no-dry-run to apply changes.")
    else:
        print("\\n✅ Database has been updated!")


if __name__ == "__main__":
    main()
