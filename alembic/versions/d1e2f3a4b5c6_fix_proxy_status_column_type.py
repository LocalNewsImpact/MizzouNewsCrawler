"""fix_proxy_status_column_type

Revision ID: d1e2f3a4b5c6
Revises: 805164cd4665
Create Date: 2025-10-31 22:45:44.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = '805164cd4665'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix proxy_status column type from Integer to String.
    
    This migration corrects a critical schema mismatch where proxy_status
    was created as Integer in migration c22022d6d3ec but the ORM model
    expects String. This mismatch causes insertion failures in PostgreSQL,
    leading to SQLite fallback and potential data loss.
    """
    # Check if we're using PostgreSQL or SQLite
    connection = op.get_bind()
    dialect_name = connection.dialect.name
    
    if dialect_name == 'postgresql':
        # PostgreSQL requires explicit type conversion
        # Use ALTER COLUMN with USING clause to convert Integer to String
        op.execute("""
            ALTER TABLE extraction_telemetry_v2
            ALTER COLUMN proxy_status TYPE VARCHAR
            USING proxy_status::VARCHAR
        """)
    elif dialect_name == 'sqlite':
        # SQLite doesn't enforce column types strictly, but we should still update
        # the schema definition for consistency. SQLite ALTER TABLE is limited,
        # so we use batch mode.
        with op.batch_alter_table('extraction_telemetry_v2',
                                  schema=None) as batch_op:
            # SQLite will accept the change without data migration
            batch_op.alter_column('proxy_status',
                                  existing_type=sa.Integer(),
                                  type_=sa.String(),
                                  existing_nullable=True)
    else:
        # For other databases, attempt a generic ALTER
        op.alter_column('extraction_telemetry_v2', 'proxy_status',
                        existing_type=sa.Integer(),
                        type_=sa.String(),
                        existing_nullable=True)


def downgrade() -> None:
    """Revert proxy_status column type from String to Integer.
    
    WARNING: This downgrade will fail if there are string values in the column
    that cannot be converted to integers (e.g., 'success', 'failed', 'bypassed').
    This is expected behavior since the String type is the correct schema.
    
    If downgrade is needed in production, manually truncate or convert the data first.
    """
    connection = op.get_bind()
    dialect_name = connection.dialect.name
    
    if dialect_name == 'postgresql':
        # Use a CASE statement to handle string values gracefully
        # Non-numeric strings will be converted to NULL
        op.execute("""
            ALTER TABLE extraction_telemetry_v2
            ALTER COLUMN proxy_status TYPE INTEGER
            USING CASE
                WHEN proxy_status IS NULL THEN NULL
                WHEN proxy_status ~ '^[0-9]+$' THEN proxy_status::INTEGER
                ELSE NULL
            END
        """)
    elif dialect_name == 'sqlite':
        with op.batch_alter_table('extraction_telemetry_v2',
                                  schema=None) as batch_op:
            batch_op.alter_column('proxy_status',
                                  existing_type=sa.String(),
                                  type_=sa.Integer(),
                                  existing_nullable=True)
    else:
        op.alter_column('extraction_telemetry_v2', 'proxy_status',
                        existing_type=sa.String(),
                        type_=sa.Integer(),
                        existing_nullable=True)
