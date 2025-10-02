#!/usr/bin/env python3
"""
Create telemetry tables for byline cleaning analysis and ML training data.

This script creates comprehensive tables to track the transformation of raw
bylines to cleaned author fields, enabling analysis of cleaning effectiveness
and generation of ML training datasets.
"""

import sqlite3
import sys
from pathlib import Path

# Add the parent directory to the path to import src modules
sys.path.append(str(Path(__file__).parent.parent))

from src.config import DATABASE_URL


def create_telemetry_tables():
    """Create all byline cleaning telemetry tables."""
    # Convert DATABASE_URL to file path (remove sqlite:/// prefix)
    db_path = DATABASE_URL.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Main telemetry table for byline cleaning transformations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS byline_cleaning_telemetry (
                id TEXT PRIMARY KEY,
                article_id TEXT,
                candidate_link_id TEXT,
                source_id TEXT,
                source_name TEXT,
                -- Raw input data
                raw_byline TEXT NOT NULL,
                raw_byline_length INTEGER,
                raw_byline_words INTEGER,
                -- Cleaning process metadata
                extraction_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                cleaning_method TEXT,
                source_canonical_name TEXT,
                -- Intermediate processing steps
                after_email_removal TEXT,
                after_source_removal TEXT,
                after_wire_service_handling TEXT,
                after_capitalization_fix TEXT,
                after_name_parsing TEXT,
                -- Final output
                final_authors_json TEXT NOT NULL,
                final_authors_count INTEGER,
                final_authors_display TEXT,
                -- Quality metrics
                confidence_score REAL DEFAULT 0.0,
                processing_time_ms REAL,
                has_wire_service BOOLEAN DEFAULT 0,
                has_email BOOLEAN DEFAULT 0,
                has_title BOOLEAN DEFAULT 0,
                has_organization BOOLEAN DEFAULT 0,
                source_name_removed BOOLEAN DEFAULT 0,
                duplicates_removed_count INTEGER DEFAULT 0,
                -- Classification flags for ML training
                likely_valid_authors BOOLEAN,
                likely_noise BOOLEAN,
                requires_manual_review BOOLEAN,
                -- Error tracking
                cleaning_errors TEXT,
                parsing_warnings TEXT,
                -- Foreign keys
                FOREIGN KEY(article_id) REFERENCES articles(id),
                FOREIGN KEY(candidate_link_id) REFERENCES candidate_links(id)
            )
        """)

        # Detailed step-by-step transformation log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS byline_transformation_steps (
                id TEXT PRIMARY KEY,
                telemetry_id TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                step_name TEXT NOT NULL,
                input_text TEXT NOT NULL,
                output_text TEXT NOT NULL,
                transformation_type TEXT,
                removed_content TEXT,
                added_content TEXT,
                confidence_delta REAL DEFAULT 0.0,
                processing_time_ms REAL,
                notes TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(telemetry_id) REFERENCES byline_cleaning_telemetry(id)
            )
        """)

        # Source-specific cleaning patterns and effectiveness
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_cleaning_analytics (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_name TEXT,
                canonical_name TEXT,
                -- Aggregated metrics over time
                total_bylines_processed INTEGER DEFAULT 0,
                avg_confidence_score REAL DEFAULT 0.0,
                avg_processing_time_ms REAL DEFAULT 0.0,
                success_rate REAL DEFAULT 0.0,
                -- Pattern analysis
                common_byline_patterns TEXT, -- JSON array of frequent patterns
                common_noise_patterns TEXT,   -- JSON array of noise patterns
                wire_service_frequency REAL DEFAULT 0.0,
                email_frequency REAL DEFAULT 0.0,
                title_frequency REAL DEFAULT 0.0,
                -- Quality indicators
                manual_review_rate REAL DEFAULT 0.0,
                duplicate_removal_rate REAL DEFAULT 0.0,
                source_name_removal_rate REAL DEFAULT 0.0,
                -- Timestamps
                first_processed DATETIME,
                last_processed DATETIME,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ML training dataset preparation table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ml_training_samples (
                id TEXT PRIMARY KEY,
                telemetry_id TEXT NOT NULL,
                sample_type TEXT NOT NULL, -- 'positive', 'negative', 'validation'
                input_features TEXT NOT NULL, -- JSON with feature vector
                expected_output TEXT NOT NULL, -- JSON with expected author list
                actual_output TEXT, -- JSON with actual cleaner output
                human_validated BOOLEAN DEFAULT 0,
                validation_timestamp DATETIME,
                validator_notes TEXT,
                training_set_version TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(telemetry_id) REFERENCES byline_cleaning_telemetry(id)
            )
        """)

        # Create indexes for efficient querying
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_byline_telemetry_article_id ON byline_cleaning_telemetry(article_id)",
            "CREATE INDEX IF NOT EXISTS idx_byline_telemetry_source_id ON byline_cleaning_telemetry(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_byline_telemetry_timestamp ON byline_cleaning_telemetry(extraction_timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_byline_telemetry_confidence ON byline_cleaning_telemetry(confidence_score)",
            "CREATE INDEX IF NOT EXISTS idx_transformation_steps_telemetry_id ON byline_transformation_steps(telemetry_id)",
            "CREATE INDEX IF NOT EXISTS idx_transformation_steps_step ON byline_transformation_steps(step_number)",
            "CREATE INDEX IF NOT EXISTS idx_source_analytics_source_id ON source_cleaning_analytics(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_ml_samples_telemetry_id ON ml_training_samples(telemetry_id)",
            "CREATE INDEX IF NOT EXISTS idx_ml_samples_type ON ml_training_samples(sample_type)",
            "CREATE INDEX IF NOT EXISTS idx_ml_samples_validated ON ml_training_samples(human_validated)"
        ]

        for index_sql in indexes:
            cursor.execute(index_sql)

        conn.commit()
        print("✅ Successfully created byline cleaning telemetry tables:")
        print("   - byline_cleaning_telemetry (main transformation tracking)")
        print("   - byline_transformation_steps (detailed step-by-step log)")
        print("   - source_cleaning_analytics (source-specific patterns)")
        print("   - ml_training_samples (ML training dataset preparation)")
        print("   - All necessary indexes created")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error creating telemetry tables: {e}")
        raise
    finally:
        conn.close()

def verify_tables():
    """Verify the created tables exist and show their structure."""
    # Convert DATABASE_URL to file path (remove sqlite:/// prefix)
    db_path = DATABASE_URL.replace('sqlite:///', '')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables = [
        'byline_cleaning_telemetry',
        'byline_transformation_steps',
        'source_cleaning_analytics',
        'ml_training_samples'
    ]

    for table in tables:
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        result = cursor.fetchone()
        if result:
            print(f"\n✅ Table '{table}' created successfully")
        else:
            print(f"❌ Table '{table}' not found")

    conn.close()

if __name__ == "__main__":
    print("Creating byline cleaning telemetry tables...")
    create_telemetry_tables()
    verify_tables()
    print("\n🎯 Telemetry system ready for ML training data collection!")
