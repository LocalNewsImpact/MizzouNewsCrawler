#!/usr/bin/env python3
"""
Fix author field format inconsistency in the articles table.

This script:
1. Converts all author fields to consistent JSON array format
2. Cleans any remaining source name contamination 
3. Handles both current JSON and plain string formats
"""

import json
import sqlite3

from src.utils.byline_cleaner import BylineCleaner


def fix_author_formats():
    """Fix author field format inconsistencies."""

    # Connect to database
    conn = sqlite3.connect('data/mizzou.db')
    cursor = conn.cursor()

    # Initialize byline cleaner
    cleaner = BylineCleaner()

    print("🔍 Analyzing author field formats...")

    # Get all articles with author data
    cursor.execute("""
        SELECT id, url, author 
        FROM articles 
        WHERE author IS NOT NULL AND author != ''
        ORDER BY id
    """)

    articles = cursor.fetchall()
    print(f"Found {len(articles)} articles with author data")

    if not articles:
        print("No articles with author data found.")
        return

    # Analyze current formats
    json_format_count = 0
    string_format_count = 0
    contaminated_count = 0
    updates_needed = []

    for article_id, url, author in articles:
        original_author = author
        needs_update = False

        # Check if it's already JSON format
        if author.startswith('[') and author.endswith(']'):
            json_format_count += 1
            try:
                # Parse JSON to check for contamination
                author_list = json.loads(author)
                if isinstance(author_list, list) and author_list:
                    # Check for source contamination
                    for author_name in author_list:
                        if any(source in author_name.lower() for source in ['webster citizen', 'citizen']):
                            contaminated_count += 1
                            needs_update = True
                            break
            except json.JSONDecodeError:
                # Invalid JSON, needs fixing
                needs_update = True
        else:
            # Plain string format
            string_format_count += 1
            needs_update = True

            # Check for contamination in string format too
            if any(source in author.lower() for source in ['webster citizen', 'citizen']):
                contaminated_count += 1

        if needs_update:
            updates_needed.append((article_id, url, original_author))

    print("\n📊 Current Format Analysis:")
    print(f"  JSON format: {json_format_count}")
    print(f"  String format: {string_format_count}")
    print(f"  With source contamination: {contaminated_count}")
    print(f"  Updates needed: {len(updates_needed)}")

    if not updates_needed:
        print("✅ All author fields are already in correct format!")
        return

    print(f"\n🔧 Processing {len(updates_needed)} author fields...")

    successful_updates = 0
    failed_updates = 0

    for article_id, url, original_author in updates_needed:
        try:
            # Parse existing author field
            if original_author.startswith('[') and original_author.endswith(']'):
                # Already JSON, try to parse and clean
                try:
                    author_list = json.loads(original_author)
                    if isinstance(author_list, list):
                        # Join for cleaning, then re-split
                        byline_text = ', '.join(author_list)
                    else:
                        byline_text = str(author_list)
                except json.JSONDecodeError:
                    # Invalid JSON, treat as string
                    byline_text = original_author.strip('[]"')
            else:
                # Plain string
                byline_text = original_author

            # Clean the byline using the enhanced cleaner
            cleaned_authors = cleaner.clean_byline(byline_text)

            # Convert to JSON format
            if cleaned_authors:
                new_author_json = json.dumps(cleaned_authors)
            else:
                new_author_json = json.dumps([])

            # Update database
            cursor.execute("""
                UPDATE articles 
                SET author = ? 
                WHERE id = ?
            """, (new_author_json, article_id))

            successful_updates += 1

            # Log significant changes
            if original_author != new_author_json:
                print(f"  ✅ Updated: '{original_author}' → '{new_author_json}'")
            else:
                print(f"  ↔️  No change: '{original_author}'")

        except Exception as e:
            print(f"  ❌ Failed to update article {article_id}: {e}")
            failed_updates += 1

    # Commit changes
    conn.commit()

    print("\n✅ Update Complete!")
    print(f"  Successful updates: {successful_updates}")
    print(f"  Failed updates: {failed_updates}")

    # Verify final state
    print("\n🔍 Verifying final state...")
    cursor.execute("""
        SELECT author, COUNT(*) as count 
        FROM articles 
        WHERE author IS NOT NULL AND author != ''
        GROUP BY author 
        ORDER BY count DESC
        LIMIT 10
    """)

    final_authors = cursor.fetchall()
    print("Top author entries after update:")
    for author, count in final_authors:
        print(f"  '{author}' ({count} articles)")

    # Check for any remaining contamination
    cursor.execute("""
        SELECT COUNT(*) 
        FROM articles 
        WHERE author IS NOT NULL 
        AND (author LIKE '%webster citizen%' OR author LIKE '%citizen%')
    """)

    remaining_contamination = cursor.fetchone()[0]
    if remaining_contamination > 0:
        print(f"⚠️  Warning: {remaining_contamination} articles still have source contamination")
    else:
        print("✅ No source contamination detected")

    conn.close()

if __name__ == "__main__":
    fix_author_formats()
