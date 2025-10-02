#!/usr/bin/env python3
"""
Migration: Add field quality tracking columns to extraction_outcomes table

This migration adds detailed field-level quality tracking to monitor:
- Missing fields  
- Quality issues (too short/long, HTML/JS artifacts, placeholder text)
- Overall quality scores per field type
- JSON columns for storing lists of specific quality issues
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

import logging

from sqlalchemy import text

from models.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Add field quality tracking columns to extraction_outcomes table."""

    migration_sql = """
    -- Add field quality issue tracking columns (JSON format for lists)
    ALTER TABLE extraction_outcomes ADD COLUMN title_quality_issues TEXT DEFAULT '[]';
    ALTER TABLE extraction_outcomes ADD COLUMN content_quality_issues TEXT DEFAULT '[]';
    ALTER TABLE extraction_outcomes ADD COLUMN author_quality_issues TEXT DEFAULT '[]';
    ALTER TABLE extraction_outcomes ADD COLUMN publish_date_quality_issues TEXT DEFAULT '[]';
    
    -- Add overall quality score column
    ALTER TABLE extraction_outcomes ADD COLUMN overall_quality_score REAL DEFAULT 1.0;
    
    -- Add field-specific quality flags for quick filtering
    ALTER TABLE extraction_outcomes ADD COLUMN title_has_issues BOOLEAN DEFAULT 0;
    ALTER TABLE extraction_outcomes ADD COLUMN content_has_issues BOOLEAN DEFAULT 0;
    ALTER TABLE extraction_outcomes ADD COLUMN author_has_issues BOOLEAN DEFAULT 0;
    ALTER TABLE extraction_outcomes ADD COLUMN publish_date_has_issues BOOLEAN DEFAULT 0;
    """

    with DatabaseManager() as db:
        try:
            logger.info("Starting field quality tracking migration...")

            # Execute migration SQL
            for statement in migration_sql.strip().split(';'):
                if statement.strip():
                    logger.info(f"Executing: {statement.strip()[:50]}...")
                    db.session.execute(text(statement))

            db.session.commit()
            logger.info("✓ Field quality tracking migration completed successfully")

            # Verify the new columns
            result = db.session.execute(text("PRAGMA table_info(extraction_outcomes)")).fetchall()
            new_columns = [row[1] for row in result if 'quality' in row[1]]
            logger.info(f"✓ Added columns: {', '.join(new_columns)}")

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            db.session.rollback()
            raise

if __name__ == "__main__":
    run_migration()
