"""add_all_predictions_jsonb_to_article_labels

Revision ID: c50ba0e981d0
Revises: 1af3ad9422f5
Create Date: 2026-02-21 11:31:53.082128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c50ba0e981d0'
down_revision: Union[str, Sequence[str], None] = '1af3ad9422f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add all_predictions JSONB column to article_labels table."""
    op.add_column(
        'article_labels',
        sa.Column('all_predictions', sa.dialects.postgresql.JSONB, nullable=True)
    )
    # Add index for querying by specific labels in the JSONB
    op.create_index(
        'ix_article_labels_all_predictions',
        'article_labels',
        ['all_predictions'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    """Remove all_predictions column from article_labels table."""
    op.drop_index('ix_article_labels_all_predictions', table_name='article_labels')
    op.drop_column('article_labels', 'all_predictions')
