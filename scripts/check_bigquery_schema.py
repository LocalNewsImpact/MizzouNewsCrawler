#!/usr/bin/env python3
"""
Check what tables and columns actually exist in PostgreSQL database.
Useful for verifying database schema and understanding table structures.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from src.models.database import DatabaseManager

def check_schema():
    """Check actual database schema."""
    print("Connecting to database...")
    db = DatabaseManager()
    
    # Get inspector
    inspector = inspect(db.engine)
    
    print("\n" + "="*80)
    print("TABLES IN DATABASE:")
    print("="*80)
    
    tables = inspector.get_table_names()
    for table in sorted(tables):
        print(f"\n📋 Table: {table}")
        print("-" * 80)
        
        columns = inspector.get_columns(table)
        for col in columns:
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            col_type = str(col['type'])
            print(f"  {col['name']:30} {col_type:20} {nullable}")
    
    print("\n" + "="*80)
    print("CHECKING MAIN TABLES:")
    print("="*80)
    
    # Check if main tables exist
    export_tables = ['articles', 'article_labels', 'article_entities']
    
    for table in export_tables:
        if table in tables:
            print(f"\n✅ {table} EXISTS")
            
            # Get sample row count
            with db.engine.connect() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar()
                print(f"   Row count: {count}")
        else:
            print(f"\n❌ {table} DOES NOT EXIST")

if __name__ == "__main__":
    check_schema()
