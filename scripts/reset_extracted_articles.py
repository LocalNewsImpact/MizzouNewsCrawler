#!/usr/bin/env python3
"""
Script to reset extracted articles back to article status for re-extraction.
"""

import sqlite3
import os

def reset_extracted_articles():
    """Reset status from 'extracted' back to 'article'."""
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'mizzou.db')
    
    if not os.path.exists(db_path):
        print(f"Database not found at: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # First, check current count
        cursor.execute("SELECT COUNT(*) FROM candidate_links WHERE status = 'extracted'")
        extracted_count = cursor.fetchone()[0]
        print(f"Found {extracted_count} articles with 'extracted' status")
        
        if extracted_count == 0:
            print("No extracted articles to reset")
            return True
            
        # Reset status
        cursor.execute("UPDATE candidate_links SET status = 'article' WHERE status = 'extracted'")
        rows_affected = cursor.rowcount
        
        # Commit the transaction
        conn.commit()
        
        print(f"Successfully reset {rows_affected} articles from 'extracted' to 'article' status")
        
        # Verify the change
        cursor.execute("SELECT COUNT(*) FROM candidate_links WHERE status = 'extracted'")
        remaining_extracted = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM candidate_links WHERE status = 'article'")
        total_articles = cursor.fetchone()[0]
        
        print(f"Verification: {remaining_extracted} extracted, {total_articles} articles")
        
        return True
        
    except Exception as e:
        print(f"Error resetting articles: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = reset_extracted_articles()
    if success:
        print("\n✅ Articles reset successfully. Ready for re-extraction with new fallback system!")
    else:
        print("\n❌ Failed to reset articles.")