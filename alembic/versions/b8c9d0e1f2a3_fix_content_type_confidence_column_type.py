"""Fix content_type_detection_telemetry confidence column type

Revision ID: b8c9d0e1f2a3
Revises: a9957c3054a4
Create Date: 2025-11-06 17:30:00.000000

This migration ensures the confidence column in content_type_detection_telemetry
is of String type, not Float/Double Precision. This fixes a production issue where
the column was created with the wrong type, causing "invalid input syntax for type
double precision: 'medium'" errors.

The migration safely handles both cases:
1. If table doesn't exist, it will be created by parent migration a9957c3054a4
2. If table exists with wrong column type, this alters it to String
3. If table already has correct type, this is a no-op
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a9957c3054a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure confidence column is String type, not numeric."""
    
    # Check if table exists
    conn = op.get_bind()
    inspector = inspect(conn)
    
    if 'content_type_detection_telemetry' not in inspector.get_table_names():
        # Table doesn't exist, parent migration will create it with correct schema
        return
    
    # Table exists - check if confidence column has wrong type
    columns = inspector.get_columns('content_type_detection_telemetry')
    confidence_col = next((col for col in columns if col['name'] == 'confidence'), None)
    
    if not confidence_col:
        # Column doesn't exist (shouldn't happen), skip
        return
    
    # Check if column type is numeric (needs fixing)
    col_type_str = str(confidence_col['type']).lower()
    is_numeric = any(t in col_type_str for t in ['float', 'double', 'real', 'numeric'])
    
    if is_numeric:
        # Column has wrong type - need to alter it
        # For PostgreSQL, we need to convert existing data
        
        # First, check if there's existing data
        result = conn.execute(text(
            "SELECT COUNT(*) FROM content_type_detection_telemetry"
        ))
        row_count = result.scalar()
        
        if row_count > 0:
            # Convert numeric values to string labels
            # Map: 0.95 -> 'very_high', 0.85 -> 'high', 0.5 -> 'medium', 0.25 -> 'low'
            conn.execute(text("""
                UPDATE content_type_detection_telemetry
                SET confidence = CASE
                    WHEN confidence >= 0.90 THEN 'very_high'
                    WHEN confidence >= 0.70 THEN 'high'
                    WHEN confidence >= 0.40 THEN 'medium'
                    ELSE 'low'
                END
                WHERE confidence IS NOT NULL
            """))
        
        # Now alter the column type using PostgreSQL-specific syntax
        # Using ALTER COLUMN with USING clause to handle conversion
        conn.execute(text("""
            ALTER TABLE content_type_detection_telemetry
            ALTER COLUMN confidence TYPE VARCHAR
            USING confidence::VARCHAR
        """))
        
        print("✅ Fixed confidence column type from numeric to VARCHAR")
    else:
        print("ℹ️  confidence column already has correct String type")


def downgrade() -> None:
    """Downgrade: Convert confidence back to numeric type.
    
    WARNING: This will lose the semantic meaning of confidence labels.
    Only use if absolutely necessary.
    """
    
    conn = op.get_bind()
    inspector = inspect(conn)
    
    if 'content_type_detection_telemetry' not in inspector.get_table_names():
        return
    
    # Convert string labels back to numeric values
    conn.execute(text("""
        UPDATE content_type_detection_telemetry
        SET confidence = CASE
            WHEN confidence = 'very_high' THEN '0.95'
            WHEN confidence = 'high' THEN '0.85'
            WHEN confidence = 'medium' THEN '0.5'
            WHEN confidence = 'low' THEN '0.25'
            ELSE '0.5'
        END
        WHERE confidence IS NOT NULL
    """))
    
    # Alter column type to DOUBLE PRECISION
    conn.execute(text("""
        ALTER TABLE content_type_detection_telemetry
        ALTER COLUMN confidence TYPE DOUBLE PRECISION
        USING confidence::DOUBLE PRECISION
    """))
    
    print("⚠️  Reverted confidence column to DOUBLE PRECISION type")
