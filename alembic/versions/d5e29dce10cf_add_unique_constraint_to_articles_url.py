"""add_unique_constraint_to_articles_url

Revision ID: d5e29dce10cf
Revises: 8656775d7ad0
Create Date: 2025-11-20 17:15:36.325353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e29dce10cf'
down_revision: Union[str, Sequence[str], None] = '8656775d7ad0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint to articles.url to prevent duplicate extractions.
    
    First, clean up existing duplicates by keeping the oldest extraction for each URL.
    """
    # Step 1: Delete duplicate articles, keeping only the oldest one per URL
    op.execute("""
        DELETE FROM articles
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY url
                           ORDER BY extracted_at ASC, created_at ASC
                       ) as rn
                FROM articles
                WHERE url IS NOT NULL
            ) t
            WHERE rn > 1
        )
    """)
    
    # Step 2: Add unique constraint
    op.create_unique_constraint('uq_articles_url', 'articles', ['url'])


def downgrade() -> None:
    """Remove unique constraint from articles.url."""
    op.drop_constraint('uq_articles_url', 'articles', type_='unique')
