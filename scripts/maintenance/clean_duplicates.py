#!/usr/bin/env python3
"""Clean up duplicate authors in existing articles."""

import json
import sqlite3


def clean_duplicate_authors():
    """Remove duplicate authors from existing articles."""
    conn = sqlite3.connect('data/mizzou.db')
    cursor = conn.cursor()

    # Get articles with author data
    cursor.execute('SELECT id, author FROM articles WHERE author IS NOT NULL AND author != ""')
    articles = cursor.fetchall()

    cleaned_count = 0

    for article_id, author_json in articles:
        if author_json and author_json.strip():
            try:
                # Parse the JSON author array
                authors = json.loads(author_json)
                if isinstance(authors, list) and len(authors) > 1:
                    # Remove duplicates while preserving order
                    seen = set()
                    cleaned_authors = []
                    for author in authors:
                        if author and author.strip():
                            author_normalized = author.strip().lower()
                            if author_normalized not in seen:
                                seen.add(author_normalized)
                                cleaned_authors.append(author.strip())

                    # Update if we removed duplicates
                    if len(cleaned_authors) < len(authors):
                        cleaned_json = json.dumps(cleaned_authors)
                        cursor.execute('UPDATE articles SET author = ? WHERE id = ?',
                                     (cleaned_json, article_id))
                        cleaned_count += 1
                        print(f'Cleaned: {authors} -> {cleaned_authors}')
            except json.JSONDecodeError:
                continue

    conn.commit()
    conn.close()

    print(f'\nCleaned {cleaned_count} articles with duplicate authors')

if __name__ == "__main__":
    clean_duplicate_authors()
