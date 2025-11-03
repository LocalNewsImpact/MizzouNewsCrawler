"""Add verification_telemetry table

Revision ID: g4h5i6j7k8l9
Revises: f3a1d2c4b6e7
Create Date: 2025-11-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g4h5i6j7k8l9'
down_revision = 'f3a1d2c4b6e7'
branch_labels = None
depends_on = None


def upgrade():
    """Create verification_telemetry table for tracking URL verification metrics.

    If an old verification_telemetry table exists with a different schema,
    rename it to preserve the data before creating the new table.
    """
    # Check if table exists and rename it if it has the old schema
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'verification_telemetry' in inspector.get_table_names():
        # Check if it has the old schema (has verification_job_id column)
        columns = [
            col['name']
            for col in inspector.get_columns('verification_telemetry')
        ]
        if 'verification_job_id' in columns and 'timestamp' not in columns:
            # Old schema - rename it to preserve data
            op.execute(
                "ALTER TABLE verification_telemetry "
                "RENAME TO verification_telemetry_old_schema"
            )

    # Now create the new table
    op.execute("""
        CREATE TABLE IF NOT EXISTS verification_telemetry (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            job_name VARCHAR(255),
            batch_size INTEGER NOT NULL,
            verified_articles INTEGER NOT NULL DEFAULT 0,
            verified_non_articles INTEGER NOT NULL DEFAULT 0,
            verification_errors INTEGER NOT NULL DEFAULT 0,
            total_processed INTEGER NOT NULL DEFAULT 0,
            batch_time_seconds REAL NOT NULL,
            avg_verification_time_ms REAL NOT NULL,
            total_time_ms REAL NOT NULL,
            sources_processed TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create indexes only if table was created or recreated
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_verification_telemetry_timestamp
            ON verification_telemetry(timestamp DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_verification_telemetry_job_name
            ON verification_telemetry(job_name)
    """)

    # Add comments
    op.execute("""
        COMMENT ON TABLE verification_telemetry IS
            'Stores batch metrics for URL verification operations using StorySniffer'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.timestamp IS
            'When the batch was processed'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.job_name IS
            'Name of the verification job/workflow'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.batch_size IS
            'Number of URLs in the batch'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.verified_articles IS
            'Count of URLs classified as articles by StorySniffer'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.verified_non_articles IS
            'Count of URLs classified as non-articles'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.verification_errors IS
            'Count of verification failures (timeouts, network errors, etc)'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.total_processed IS
            'Total URLs successfully processed (articles + non-articles)'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.batch_time_seconds IS
            'Wall-clock time to process the entire batch'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.avg_verification_time_ms IS
            'Average verification time per URL in milliseconds'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.total_time_ms IS
            'Cumulative verification time for all URLs'
    """)
    op.execute("""
        COMMENT ON COLUMN verification_telemetry.sources_processed IS
            'JSON array of source names included in this batch'
    """)


def downgrade():
    """Drop verification_telemetry table."""
    op.execute("""
        DROP INDEX IF EXISTS idx_verification_telemetry_job_name;
        DROP INDEX IF EXISTS idx_verification_telemetry_timestamp;
        DROP TABLE IF EXISTS verification_telemetry CASCADE;
    """)
