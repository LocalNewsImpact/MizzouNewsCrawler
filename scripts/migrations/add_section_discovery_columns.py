"""
Add section discovery columns to `sources` table for adaptive section-based
article discovery. This migration adds:
- discovered_sections: JSON column to store section URLs and performance metrics
- section_discovery_enabled: Boolean flag to enable/disable section discovery
- section_last_updated: Timestamp of last section discovery update

Usage: python scripts/migrations/add_section_discovery_columns.py
"""

import os
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text

from src.models.database import DatabaseManager


def run_migration():
    """Add section discovery columns to sources table."""
    
    # Get database URL from environment or use default
    database_url = os.getenv("DATABASE_URL", "sqlite:///data/mizzou.db")
    
    print(f"Connecting to database: {database_url}")
    db = DatabaseManager(database_url)
    
    try:
        with db.engine.begin() as conn:
            dialect = conn.dialect.name
            print(f"Database dialect: {dialect}")
            
            # Check if columns already exist
            if dialect == "postgresql":
                result = conn.execute(
                    text(
                        """
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'sources' 
                        AND column_name IN (
                            'discovered_sections',
                            'section_discovery_enabled', 
                            'section_last_updated'
                        )
                        """
                    )
                )
                existing_columns = {row[0] for row in result.fetchall()}
            else:
                # SQLite
                result = conn.execute(text("PRAGMA table_info(sources)"))
                existing_columns = {row[1] for row in result.fetchall()}
            
            columns_to_add = []
            if "discovered_sections" not in existing_columns:
                columns_to_add.append("discovered_sections")
            if "section_discovery_enabled" not in existing_columns:
                columns_to_add.append("section_discovery_enabled")
            if "section_last_updated" not in existing_columns:
                columns_to_add.append("section_last_updated")
            
            if not columns_to_add:
                print("✓ All section discovery columns already exist")
                return True
            
            print(f"Adding columns: {', '.join(columns_to_add)}")
            
            # Add discovered_sections column
            if "discovered_sections" in columns_to_add:
                if dialect == "postgresql":
                    conn.execute(
                        text("ALTER TABLE sources ADD COLUMN discovered_sections JSONB")
                    )
                else:
                    conn.execute(
                        text("ALTER TABLE sources ADD COLUMN discovered_sections TEXT")
                    )
                print("✓ Added discovered_sections column")
            
            # Add section_discovery_enabled column
            if "section_discovery_enabled" in columns_to_add:
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            """
                            ALTER TABLE sources 
                            ADD COLUMN section_discovery_enabled BOOLEAN 
                            NOT NULL DEFAULT TRUE
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            ALTER TABLE sources 
                            ADD COLUMN section_discovery_enabled INTEGER 
                            NOT NULL DEFAULT 1
                            """
                        )
                    )
                print("✓ Added section_discovery_enabled column")
            
            # Add section_last_updated column
            if "section_last_updated" in columns_to_add:
                conn.execute(
                    text("ALTER TABLE sources ADD COLUMN section_last_updated TIMESTAMP")
                )
                print("✓ Added section_last_updated column")
            
            print("✓ Migration completed successfully")
            return True
            
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
