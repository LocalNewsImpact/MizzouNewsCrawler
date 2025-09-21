#!/usr/bin/env python3
"""
Migration script to add extraction_outcomes table to the telemetry database.

Usage:
    python scripts/add_extraction_outcomes_table.py
"""

import sqlite3
from pathlib import Path


def get_db_path():
    """Get the path to the telemetry database."""
    return Path(__file__).parent.parent / "data" / "mizzou.db"


def create_extraction_outcomes_table():
    """Create the extraction_outcomes table for extraction telemetry."""
    
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return 1
    
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS extraction_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id TEXT NOT NULL,
        article_id INTEGER NOT NULL,
        url TEXT NOT NULL,
        outcome TEXT NOT NULL,
        extraction_time_ms REAL NOT NULL DEFAULT 0.0,
        start_time TIMESTAMP NOT NULL,
        end_time TIMESTAMP NOT NULL,
        http_status_code INTEGER,
        response_size_bytes INTEGER,
        has_title BOOLEAN NOT NULL DEFAULT 0,
        has_content BOOLEAN NOT NULL DEFAULT 0,
        has_author BOOLEAN NOT NULL DEFAULT 0,
        has_publish_date BOOLEAN NOT NULL DEFAULT 0,
        content_length INTEGER,
        title_length INTEGER,
        author_count INTEGER,
        content_quality_score REAL,
        error_message TEXT,
        error_type TEXT,
        is_success BOOLEAN NOT NULL DEFAULT 0,
        is_content_success BOOLEAN NOT NULL DEFAULT 0,
        is_technical_failure BOOLEAN NOT NULL DEFAULT 0,
        is_bot_protection BOOLEAN NOT NULL DEFAULT 0,
        metadata TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    
    # Create indexes for efficient querying
    indexes = [
        ("CREATE INDEX IF NOT EXISTS idx_extraction_operation "
         "ON extraction_outcomes (operation_id)"),
        ("CREATE INDEX IF NOT EXISTS idx_extraction_article "
         "ON extraction_outcomes (article_id)"),
        ("CREATE INDEX IF NOT EXISTS idx_extraction_outcome "
         "ON extraction_outcomes (outcome)"),
        ("CREATE INDEX IF NOT EXISTS idx_extraction_success "
         "ON extraction_outcomes (is_success)"),
        ("CREATE INDEX IF NOT EXISTS idx_extraction_content_success "
         "ON extraction_outcomes (is_content_success)"),
        ("CREATE INDEX IF NOT EXISTS idx_extraction_timestamp "
         "ON extraction_outcomes (timestamp)"),
        ("CREATE INDEX IF NOT EXISTS idx_extraction_url "
         "ON extraction_outcomes (url)"),
        ("CREATE INDEX IF NOT EXISTS idx_extraction_quality "
         "ON extraction_outcomes (content_quality_score)"),
    ]
    
    try:
        with sqlite3.connect(db_path) as conn:
            print("Creating extraction_outcomes table...")
            conn.execute(create_table_sql)
            
            print("Creating indexes...")
            for index_sql in indexes:
                conn.execute(index_sql)
            
            conn.commit()
            print("✓ extraction_outcomes table created successfully!")
            
    except Exception as e:
        print(f"Error creating extraction_outcomes table: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(create_extraction_outcomes_table())
