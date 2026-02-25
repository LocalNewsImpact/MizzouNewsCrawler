"""add_rss_tracking_columns_to_sources

Revision ID: d7e8f9a0b1c2
Revises: c50ba0e981d0
Create Date: 2026-02-25 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c50ba0e981d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add RSS tracking columns to sources table."""
    op.add_column(
        'sources',
        sa.Column('last_successful_rss_at', sa.DateTime(), nullable=True)
    )
    op.add_column(
        'sources',
        sa.Column('skip_rss_until', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Remove RSS tracking columns from sources table."""
    op.drop_column('sources', 'skip_rss_until')
    op.drop_column('sources', 'last_successful_rss_at')
