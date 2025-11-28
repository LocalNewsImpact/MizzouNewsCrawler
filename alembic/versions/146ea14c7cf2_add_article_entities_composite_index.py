"""add_article_entities_composite_index

Revision ID: 146ea14c7cf2
Revises: 65bdb80e3f80
Create Date: 2025-11-27 18:01:29.152684

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '146ea14c7cf2'
down_revision: Union[str, Sequence[str], None] = '65bdb80e3f80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add composite index for fast article entity lookups."""
    # Composite index on (article_id, created_at) for:
    # 1. Finding articles with entities (GROUP BY article_id)
    # 2. Recent entity extraction queries (WHERE created_at >= X)
    # This enables index-only scans for COUNT DISTINCT queries
    op.create_index(
        'ix_article_entities_article_id_created_at',
        'article_entities',
        ['article_id', 'created_at'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema - remove composite index."""
    op.drop_index('ix_article_entities_article_id_created_at', table_name='article_entities')
