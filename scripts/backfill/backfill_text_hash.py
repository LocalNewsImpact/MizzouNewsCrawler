#!/usr/bin/env python3
"""
Backfill text_hash for existing articles.
"""

import hashlib

from sqlalchemy import text

from src.models.database import DatabaseManager


def calculate_content_hash(content: str) -> str:
    """Calculate SHA256 hash of content for deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main():
    """Backfill text_hash for articles that have content but no text_hash."""
    db = DatabaseManager()

    with db.engine.connect() as conn:
        # Get articles with content but no text_hash
        result = conn.execute(
            text("""
            SELECT id, content, text
            FROM articles
            WHERE (content IS NOT NULL AND content != '')
            AND (text_hash IS NULL OR text_hash = '')
        """)
        )

        articles = result.fetchall()
        print(f"Found {len(articles)} articles to backfill")

        updated_count = 0
        for article in articles:
            article_id, content, text_content = article

            # Use content if available, fallback to text
            text_to_hash = content or text_content or ""

            if text_to_hash:
                text_hash = calculate_content_hash(text_to_hash)

                # Update the article with calculated text_hash
                conn.execute(
                    text("""
                    UPDATE articles
                    SET text_hash = :text_hash
                    WHERE id = :id
                """),
                    {"text_hash": text_hash, "id": article_id},
                )

                updated_count += 1
                if updated_count % 50 == 0:
                    print(f"Updated {updated_count} articles...")

        conn.commit()
        print(f"Successfully backfilled text_hash for {updated_count} articles")


if __name__ == "__main__":
    main()
