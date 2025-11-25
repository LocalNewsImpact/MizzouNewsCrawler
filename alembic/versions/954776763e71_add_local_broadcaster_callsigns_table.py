"""add_local_broadcaster_callsigns_table

Revision ID: 954776763e71
Revises: d5e29dce10cf
Create Date: 2025-11-22 19:54:08.682659

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '954776763e71'
down_revision: Union[str, Sequence[str], None] = 'd5e29dce10cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if table already exists (idempotent migration)
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    
    if 'local_broadcaster_callsigns' in inspector.get_table_names():
        # Table already exists, skip creation
        return
    
    op.create_table(
        'local_broadcaster_callsigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'callsign', sa.String(length=10), nullable=False,
            comment='FCC callsign (e.g., KMIZ, KOMU)'
        ),
        sa.Column(
            'source_id', sa.String(), nullable=True,
            comment='Foreign key to sources table (UUID)'
        ),
        sa.Column(
            'dataset', sa.String(length=50), nullable=False,
            comment='Dataset identifier (e.g., missouri)'
        ),
        sa.Column(
            'market_name', sa.String(length=100), nullable=True,
            comment='Market name (e.g., Columbia-Jefferson City)'
        ),
        sa.Column(
            'station_type', sa.String(length=20), nullable=True,
            comment='TV, Radio, or Digital'
        ),
        sa.Column('notes', sa.Text(), nullable=True,
                  comment='Additional context'),
        sa.Column(
            'created_at', sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP'),
            nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP'),
            nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['source_id'], ['sources.id'], ondelete='SET NULL'
        ),
        sa.UniqueConstraint(
            'callsign', 'dataset', name='uix_callsign_dataset'
        ),
        comment='Local broadcaster callsigns for wire detection'
    )
    
    # Create indexes for efficient lookups
    op.create_index(
        'ix_local_broadcaster_callsigns_callsign',
        'local_broadcaster_callsigns',
        ['callsign']
    )
    op.create_index(
        'ix_local_broadcaster_callsigns_dataset',
        'local_broadcaster_callsigns',
        ['dataset']
    )
    op.create_index(
        'ix_local_broadcaster_callsigns_source_id',
        'local_broadcaster_callsigns',
        ['source_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_local_broadcaster_callsigns_source_id',
        table_name='local_broadcaster_callsigns'
    )
    op.drop_index(
        'ix_local_broadcaster_callsigns_dataset',
        table_name='local_broadcaster_callsigns'
    )
    op.drop_index(
        'ix_local_broadcaster_callsigns_callsign',
        table_name='local_broadcaster_callsigns'
    )
    op.drop_table('local_broadcaster_callsigns')
