"""Add cron_enabled flag to datasets

Revision ID: 1c15007392b3
Revises: 9f8e7d6c5b4a
Create Date: 2025-10-11 12:36:45.767106

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c15007392b3'
down_revision: Union[str, Sequence[str], None] = '9f8e7d6c5b4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cron_enabled column to datasets table.
    
    This flag controls whether a dataset should be included in automated
    cron jobs. Existing datasets default to True (enabled for cron).
    New custom source lists should set this to False to prevent accidental
    inclusion in automated processing.
    """
    # Check if column already exists before adding
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('datasets')]
    
    if 'cron_enabled' not in columns:
        # Add column with default True for existing datasets
        # Note: server_default='1' ensures existing datasets are cron-enabled
        # New datasets will use Python-level default from the model
        op.add_column(
            'datasets',
            sa.Column('cron_enabled', sa.Boolean(), nullable=False, server_default='1')
        )


def downgrade() -> None:
    """Remove cron_enabled column from datasets table."""
    # Check if column exists before dropping
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('datasets')]
    
    if 'cron_enabled' in columns:
        op.drop_column('datasets', 'cron_enabled')
