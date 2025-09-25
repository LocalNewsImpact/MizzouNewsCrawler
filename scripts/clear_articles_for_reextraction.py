#!/usr/bin/env python3
"""
Script to clear the articles table before running extraction with new fallback system.
"""

import sqlite3
import os

def clear_articles_table():
    """Clear all articles to allow fresh extraction with new fallback system."""
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'mizzou.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found at: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Check current count
        cursor.execute("SELECT COUNT(*) FROM articles")
        current_count = cursor.fetchone()[0]
        print(f"Current articles in database: {current_count}")
        
        if current_count == 0:
            print("Articles table is already empty")
            return True
            
        # Clear the articles table
        cursor.execute("DELETE FROM articles")
        rows_deleted = cursor.rowcount
        
        # Reset the sequence/autoincrement if needed
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='articles'")
        
        # Commit the transaction
        conn.commit()
        
        print(f"Successfully deleted {rows_deleted} articles from database")
        
        # Verify the table is empty
        cursor.execute("SELECT COUNT(*) FROM articles")
        remaining_count = cursor.fetchone()[0]
        
        print(f"Verification: {remaining_count} articles remaining")
        
        return True
        
    except Exception as e:
        print(f"Error clearing articles: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("🗑️  Clearing articles table for fresh extraction with new fallback system")
    print("=" * 70)
    
    success = clear_articles_table()
    
    if success:
        print("\n✅ Articles table cleared successfully!")
        print("Ready to run extraction with enhanced three-tier fallback system:")
        print("  newspaper4k → BeautifulSoup → Selenium")
        print("\nNext step: Run extraction command")
    else:
        print("\n❌ Failed to clear articles table.")