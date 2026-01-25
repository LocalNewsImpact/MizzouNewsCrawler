"""add url_path_filters table

Revision ID: ebac28990451
Revises: 305f6389a934
Create Date: 2025-12-19 16:35:01.269179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebac28990451'
down_revision: Union[str, Sequence[str], None] = '305f6389a934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create url_path_filters table
    op.create_table(
        'url_path_filters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('path_pattern', sa.String(length=200), nullable=False, comment='URL path pattern to filter (e.g., /video/, /gallery/)'),
        sa.Column('filter_type', sa.String(length=50), nullable=False, server_default='prefix', comment='Match type: prefix, suffix, contains, regex'),
        sa.Column('reason', sa.String(length=200), nullable=True, comment='Why this pattern is filtered (e.g., \'video content\')'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true', comment='Whether this filter is active'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path_pattern'),
        comment='URL path filters for non-article content'
    )

    # Create indexes
    op.create_index('ix_url_path_filters_path_pattern', 'url_path_filters', ['path_pattern'])
    op.create_index('ix_url_path_filters_active', 'url_path_filters', ['active'])

    # Seed with common non-article path patterns
    op.execute("""
        INSERT INTO url_path_filters (path_pattern, filter_type, reason, active, notes)
        VALUES
            ('/video/', 'prefix', 'Video content', true, 'Filter top-level /video/ paths'),
            ('/videos/', 'prefix', 'Video content', true, 'Filter top-level /videos/ paths'),
            ('/gallery/', 'prefix', 'Photo galleries', true, 'Filter photo gallery pages'),
            ('/galleries/', 'prefix', 'Photo galleries', true, 'Filter photo gallery pages'),
            ('/tag/', 'prefix', 'Tag pages', true, 'Filter tag/taxonomy pages'),
            ('/tags/', 'prefix', 'Tag pages', true, 'Filter tag/taxonomy pages'),
            ('/category/', 'prefix', 'Category pages', true, 'Filter category archive pages'),
            ('/author/', 'prefix', 'Author pages', true, 'Filter author bio/archive pages')
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_url_path_filters_active', table_name='url_path_filters')
    op.drop_index('ix_url_path_filters_path_pattern', table_name='url_path_filters')
    op.drop_table('url_path_filters')
