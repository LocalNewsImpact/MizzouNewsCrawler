#!/usr/bin/env python3
"""
Add Wire column to articles table for tracking wire service content.

This migration adds a new 'wire' column to the articles table to store
wire service names that were detected and removed from the byline field.
This enables proper classification and filtering of wire service content.
"""

import sqlite3
import sys
from pathlib import Path

# Add src directory to path for imports
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

try:
    from utils.database import DatabaseManager
except ImportError:
    # Fallback: connect directly to database
    print("⚠️  Could not import DatabaseManager, using direct SQLite connection")
    DatabaseManager = Nonehon3
"""
Add Wire column to articles table for tracking wire service content.

This migration adds a new 'wire' column to the articles table to store
wire service names that were detected and removed from the byline field.
This enables proper classification and filtering of wire service content.
"""

import sqlite3
import sys
from pathlib import Path

# Add src directory to path for imports
src_path = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(src_path))

from utils.database import DatabaseManager


def add_wire_column():
    """Add Wire column to articles table."""
    
    print("🔧 Adding Wire column to articles table...")
    
    try:
        # Initialize database manager
        db_manager = DatabaseManager()
        
        # Check if column already exists
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get table info
            cursor.execute("PRAGMA table_info(articles)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'wire' in columns:
                print("✅ Wire column already exists in articles table")
                return True
            
            # Add the Wire column
            cursor.execute("""
                ALTER TABLE articles 
                ADD COLUMN wire TEXT DEFAULT NULL
            """)
            
            # Create index for efficient querying
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_wire 
                ON articles(wire)
            """)
            
            conn.commit()
            
            print("✅ Successfully added Wire column to articles table")
            print("✅ Created index on Wire column for efficient querying")
            
            # Get count of articles for reference
            cursor.execute("SELECT COUNT(*) FROM articles")
            article_count = cursor.fetchone()[0]
            print(f"📊 Articles table now has {article_count:,} records")
            
            return True
            
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


def verify_migration():
    """Verify the migration was successful."""
    
    print("\n🔍 Verifying Wire column migration...")
    
    try:
        db_manager = DatabaseManager()
        
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check table schema
            cursor.execute("PRAGMA table_info(articles)")
            columns = cursor.fetchall()
            
            wire_column = None
            for col in columns:
                if col[1] == 'wire':
                    wire_column = col
                    break
            
            if wire_column:
                print(f"✅ Wire column found: {wire_column}")
                print(f"   - Name: {wire_column[1]}")
                print(f"   - Type: {wire_column[2]}")
                print(f"   - Not Null: {bool(wire_column[3])}")
                print(f"   - Default: {wire_column[4]}")
            else:
                print("❌ Wire column not found!")
                return False
            
            # Check index
            cursor.execute("PRAGMA index_list(articles)")
            indexes = cursor.fetchall()
            
            wire_index_found = False
            for index in indexes:
                if 'wire' in index[1]:
                    wire_index_found = True
                    print(f"✅ Wire index found: {index[1]}")
                    break
            
            if not wire_index_found:
                print("⚠️  Wire index not found (this may be okay)")
            
            # Test a simple query
            cursor.execute("SELECT COUNT(*) FROM articles WHERE wire IS NULL")
            null_count = cursor.fetchone()[0]
            print(f"📊 Articles with NULL wire field: {null_count:,}")
            
            return True
            
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Starting Wire column migration...")
    print("=" * 50)
    
    # Run migration
    success = add_wire_column()
    
    if success:
        # Verify migration
        verify_migration()
        print("\n🎉 Migration completed successfully!")
        print("\n📋 Next steps:")
        print("   1. Update article processing to populate Wire column")
        print("   2. Implement wire service filtering logic")
        print("   3. Test with sample bylines containing wire services")
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)