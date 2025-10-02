#!/usr/bin/env python3

# Add discovery_attempted column to sources table

import sqlite3
from pathlib import Path


def add_discovery_attempted_column():
    db_path = "data/mizzou.db"

    if not Path(db_path).exists():
        print(f"Database not found at {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(sources)")
        columns = [row[1] for row in cursor.fetchall()]

        if "discovery_attempted" in columns:
            print("discovery_attempted column already exists")
            return True

        # Add the column
        cursor.execute("""
            ALTER TABLE sources 
            ADD COLUMN discovery_attempted TIMESTAMP
        """)

        conn.commit()
        print("Successfully added discovery_attempted column to sources table")

        # Verify the column was added
        cursor.execute("PRAGMA table_info(sources)")
        columns_after = [row[1] for row in cursor.fetchall()]
        print(f"Columns after migration: {columns_after}")

        return True

    except Exception as e:
        print(f"Error adding column: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    add_discovery_attempted_column()
