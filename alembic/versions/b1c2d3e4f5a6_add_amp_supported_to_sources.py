"""add amp_supported to sources

Revision ID: b1c2d3e4f5a6
Revises: a323ff14aed4
Create Date: 2026-01-21 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a323ff14aed4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add amp_supported column to sources table."""
    # Add amp_supported boolean column
    op.add_column(
        'sources',
        sa.Column(
            'amp_supported',
            sa.Boolean(),
            nullable=True,
            server_default=sa.text('FALSE'),
            comment='Whether source supports AMP pages for PerimeterX bypass'
        )
    )
    
    # Add index for performance
    op.create_index(
        'ix_sources_amp_supported',
        'sources',
        ['amp_supported'],
        unique=False
    )


def downgrade() -> None:
    """Remove amp_supported column from sources table."""
    op.drop_index('ix_sources_amp_supported', table_name='sources')
    op.drop_column('sources', 'amp_supported')
