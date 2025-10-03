#!/usr/bin/env python3

import sqlite3
from src.utils.byline_cleaner import BylineCleaner


def test_real_author_data():
    """Test the byline cleaner on real author data from the articles table."""

    # Connect to the database
    db_path = "data/mizzou.db"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Query articles with author data
        query = """
        SELECT id, url, author, title 
        FROM articles 
        WHERE author IS NOT NULL 
        AND author != '' 
        AND author NOT LIKE '%None%'
        ORDER BY id DESC
        LIMIT 20
        """

        cursor.execute(query)
        articles = cursor.fetchall()

        if not articles:
            print("No articles with author data found in database.")
            return

        # Initialize the byline cleaner
        cleaner = BylineCleaner()

        print("Testing BylineCleaner on real author data from articles table:")
        print("=" * 80)
        print(f"Found {len(articles)} articles with author data\n")

        for article_id, url, author, title in articles:
            print(f"Article ID: {article_id}")
            print(f"URL: {url[:60]}..." if len(url) > 60 else f"URL: {url}")
            print(f"Title: {title[:60]}..." if len(title) > 60 else f"Title: {title}")
            print(f"Original Author: '{author}'")

            # Clean the author field
            try:
                cleaned_result = cleaner.clean_byline(author, return_json=True)
                print(f"Cleaned Authors: {cleaned_result['authors']}")
                print(f"Count: {cleaned_result['count']}")
                print(f"Multiple: {cleaned_result['has_multiple_authors']}")

                # Show the difference
                if str(cleaned_result["authors"]) != author:
                    print("🔄 CHANGED - Original vs Cleaned different")
                else:
                    print("✅ NO CHANGE - Already clean")

            except Exception as e:
                print(f"❌ ERROR cleaning author: {e}")

            print("-" * 60)

        conn.close()

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Error: {e}")


def test_problematic_authors():
    """Test specific problematic author patterns that might exist."""

    cleaner = BylineCleaner()

    # Common problematic patterns we might find in real data
    test_cases = [
        "By Staff",
        "Staff Writer",
        "News Staff",
        "AP",
        "Associated Press",
        "John Doe, Staff Reporter",
        "Jane Smith and Bob Jones, Editors",
        "Reporter",
        "Editor",
        "News Team",
        "By John Smith, Editor",
        "Sarah Johnson, sarah.johnson@news.com",
        "Mike Davis | Staff Writer",
        "- Reporter Name",
        "Staff | News Department",
    ]

    print("\nTesting common problematic author patterns:")
    print("=" * 50)

    for test_case in test_cases:
        result = cleaner.clean_byline(test_case, return_json=True)
        authors = result["authors"]

        print(f"'{test_case}' → {authors}")
        if not authors:
            print("  ⚠️  Results in empty authors list")
        elif len(authors) == 1 and len(authors[0].split()) >= 2:
            print("  ✅ Good - proper name(s) extracted")
        elif any(
            word.lower() in cleaner.JOURNALISM_NOUNS
            for author in authors
            for word in author.split()
        ):
            print("  ⚠️  Still contains journalism terms")
        else:
            print("  ✅ Cleaned successfully")


if __name__ == "__main__":
    test_real_author_data()
    test_problematic_authors()
