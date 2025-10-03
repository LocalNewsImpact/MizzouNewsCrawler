#!/usr/bin/env python3
"""
Dry run test of byline cleaner on actual articles table data.
"""

import sys
import sqlite3
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent))

from src.utils.byline_cleaner import BylineCleaner


def test_on_articles_table():
    """Test byline cleaner on real articles table data."""

    # Connect to the database
    db_path = Path(__file__).parent / "data" / "mizzou.db"
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get a sample of articles with bylines
    query = """
    SELECT id, url, author, title 
    FROM articles 
    WHERE author IS NOT NULL 
    AND author != '' 
    AND author != 'NULL'
    ORDER BY RANDOM() 
    LIMIT 20
    """

    try:
        cursor.execute(query)
        articles = cursor.fetchall()

        if not articles:
            print("No articles with bylines found in database")
            return

        cleaner = BylineCleaner()

        print("Byline Cleaner Dry Run on Articles Table")
        print("=" * 60)
        print(f"Testing {len(articles)} random articles with bylines\n")

        for i, (article_id, url, author, title) in enumerate(articles, 1):
            print(f"Article {i} (ID: {article_id}):")
            print(f"  Title: {title[:80]}{'...' if len(title) > 80 else ''}")
            print(f"  URL: {url}")
            print(f"  Original Author: '{author}'")

            # Clean the byline
            cleaned_authors = cleaner.clean_byline(author, return_json=False)
            cleaned_json = cleaner.clean_byline(author, return_json=True)

            print("  📊 FINAL DATABASE STORAGE:")
            print(f"     Array to store: {cleaned_authors}")
            print(f"     Individual authors: {len(cleaned_authors)}")
            for j, auth in enumerate(cleaned_authors, 1):
                print(f"       Author {j}: '{auth}'")

            print("  📈 METADATA:")
            print(f"     Author Count: {cleaned_json['count']}")
            print(f"     Primary Author: '{cleaned_json['primary_author']}'")
            if cleaned_json["has_multiple_authors"]:
                print("     Multiple Authors: Yes")

            # Check for wire services
            if cleaned_authors and any(
                "press" in author.lower()
                or "reuters" in author.lower()
                or "ap" in author.lower()
                or "cnn" in author.lower()
                for author in cleaned_authors
            ):
                print("  🔍 Wire Service: Detected for future filtering")

            # Show what would be searchable
            print("  🔍 SEARCHABLE TERMS:")
            search_terms = []
            for auth in cleaned_authors:
                search_terms.extend(auth.lower().split())
            print(f"     Search terms: {search_terms}")

            print()

        # Summary statistics
        all_cleaned = []
        wire_services = 0
        multiple_authors = 0

        cursor.execute(query)  # Re-run to get fresh data
        articles = cursor.fetchall()

        for _, _, author, _ in articles:
            cleaned = cleaner.clean_byline(author, return_json=True)
            all_cleaned.append(cleaned)

            if cleaned["has_multiple_authors"]:
                multiple_authors += 1

            # Check for wire services (simplified)
            if any(ws in author.lower() for ws in ["press", "reuters", "ap", "cnn"]):
                wire_services += 1

        print("=" * 60)
        print("SUMMARY STATISTICS:")
        print(f"Total articles tested: {len(all_cleaned)}")
        print(f"Articles with multiple authors: {multiple_authors}")
        print(f"Potential wire service articles: {wire_services}")
        print(
            f"Articles with clean author data: {len([c for c in all_cleaned if c['count'] > 0])}"
        )
        print(
            f"Articles with no extractable authors: {len([c for c in all_cleaned if c['count'] == 0])}"
        )

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    test_on_articles_table()
