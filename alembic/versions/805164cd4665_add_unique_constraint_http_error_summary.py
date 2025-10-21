"""add_unique_constraint_http_error_summary

Revision ID: 805164cd4665
Revises: c22022d6d3ec
Create Date: 2025-10-20 16:57:38.434234

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '805164cd4665'
down_revision: Union[str, Sequence[str], None] = 'c22022d6d3ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add UNIQUE constraint on (host, status_code) to support ON CONFLICT
    # This is required for the upsert operation in comprehensive_telemetry.py
    
    # For PostgreSQL: Use create_unique_constraint
    # For SQLite: Must use batch mode (table recreation)
    
    with op.batch_alter_table('http_error_summary', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_http_error_summary_host_status',
            ['host', 'status_code']
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove UNIQUE constraint
    with op.batch_alter_table('http_error_summary', schema=None) as batch_op:
        batch_op.drop_constraint(
            'uq_http_error_summary_host_status',
            type_='unique'
        )
