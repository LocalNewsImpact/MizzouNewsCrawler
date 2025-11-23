"""add_wire_services_table

Revision ID: 7d013dc70116
Revises: 954776763e71
Create Date: 2025-11-23 08:18:35.578928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d013dc70116'
down_revision: Union[str, Sequence[str], None] = '954776763e71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'wire_services',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'service_name', sa.String(length=100), nullable=False,
            comment='Canonical service name (e.g., Associated Press)'
        ),
        sa.Column(
            'pattern', sa.String(length=500), nullable=False,
            comment='Regex pattern to match service in content'
        ),
        sa.Column(
            'pattern_type', sa.String(length=20), nullable=False,
            comment='dateline, byline, or attribution'
        ),
        sa.Column(
            'case_sensitive', sa.Boolean(), nullable=False,
            server_default='false',
            comment='Whether pattern matching is case-sensitive'
        ),
        sa.Column(
            'priority', sa.Integer(), nullable=False, server_default='100',
            comment='Detection priority (lower = higher priority)'
        ),
        sa.Column(
            'active', sa.Boolean(), nullable=False, server_default='true',
            comment='Whether this pattern is active'
        ),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(), nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP')
        ),
        sa.Column(
            'updated_at', sa.DateTime(), nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP')
        ),
        sa.PrimaryKeyConstraint('id'),
        comment='Wire service detection patterns'
    )
    
    # Create indexes
    op.create_index(
        'ix_wire_services_service_name',
        'wire_services',
        ['service_name']
    )
    op.create_index(
        'ix_wire_services_pattern_type',
        'wire_services',
        ['pattern_type']
    )
    op.create_index(
        'ix_wire_services_active',
        'wire_services',
        ['active']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_wire_services_active', table_name='wire_services')
    op.drop_index(
        'ix_wire_services_pattern_type',
        table_name='wire_services'
    )
    op.drop_index(
        'ix_wire_services_service_name',
        table_name='wire_services'
    )
    op.drop_table('wire_services')
