"""add_pipeline_status_indexes

Revision ID: 65bdb80e3f80
Revises: 5a41e9c2e0d9
Create Date: 2025-11-27 16:33:59.511426

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '65bdb80e3f80'
down_revision: Union[str, Sequence[str], None] = '5a41e9c2e0d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add timestamp indexes for pipeline-status query performance."""
    # Index on candidate_links.processed_at for Discovery query
    # This query filters: processed_at < NOW() - INTERVAL '7 days'
    op.create_index(
        'ix_candidate_links_processed_at',
        'candidate_links',
        ['processed_at'],
        unique=False
    )
    
    # Index on candidate_links.discovered_at for Discovery/Verification queries
    # These queries filter: discovered_at >= :cutoff
    op.create_index(
        'ix_candidate_links_discovered_at',
        'candidate_links',
        ['discovered_at'],
        unique=False
    )
    
    # Index on articles.extracted_at for Extraction and Overall Health queries
    # These queries filter: extracted_at >= :cutoff
    op.create_index(
        'ix_articles_extracted_at',
        'articles',
        ['extracted_at'],
        unique=False
    )
    
    # Index on article_entities.created_at for Entity Extraction recent activity query
    # This query was taking 39.5s without index: created_at >= :cutoff
    op.create_index(
        'ix_article_entities_created_at',
        'article_entities',
        ['created_at'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema - remove timestamp indexes."""
    op.drop_index('ix_article_entities_created_at', table_name='article_entities')
    op.drop_index('ix_articles_extracted_at', table_name='articles')
    op.drop_index('ix_candidate_links_discovered_at', table_name='candidate_links')
    op.drop_index('ix_candidate_links_processed_at', table_name='candidate_links')
