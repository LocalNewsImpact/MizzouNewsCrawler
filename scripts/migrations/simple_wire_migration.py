#!/usr/bin/env python3
"""
Simple migration to add Wire column to articles table.
"""

import sqlite3
from pathlib import Path


def main():
    """Add Wire column to articles table."""

    print("🔧 Adding Wire column to articles table...")

    # Find database
    db_paths = [Path("data/mizzou.db"), Path("mizzou.db"), Path("news_crawler.db")]

    db_path = None
    for path in db_paths:
        if path.exists():
            db_path = path
            break

    if not db_path:
        print("❌ Database not found!")
        return False

    print(f"📁 Using database: {db_path}")

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(articles)")
        columns = [row[1] for row in cursor.fetchall()]

        if "wire" in columns:
            print("✅ Wire column already exists")
            conn.close()
            return True

        # Add the Wire column
        print("⚡ Adding Wire column...")
        cursor.execute("ALTER TABLE articles ADD COLUMN wire TEXT DEFAULT NULL")

        # Create index
        print("📊 Creating index...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_wire ON articles(wire)")

        conn.commit()

        # Verify
        cursor.execute("SELECT COUNT(*) FROM articles")
        count = cursor.fetchone()[0]

        print("✅ Wire column added successfully!")
        print(f"📊 Articles table has {count:,} records")

        conn.close()
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = main()
    if success:
        print("🎉 Migration completed!")
    else:
        print("💥 Migration failed!")
        exit(1)
