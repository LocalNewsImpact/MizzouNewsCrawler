"""add_performance_indexes_for_work_queue_and_foreign_keys

Revision ID: 5a41e9c2e0d9
Revises: f224b4c09ef3
Create Date: 2025-11-27 06:44:25.064440

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a41e9c2e0d9'
down_revision: Union[str, Sequence[str], None] = 'f224b4c09ef3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance indexes for critical queries and missing foreign keys.
    
    Key improvements:
    1. Composite index (status, source) for work queue domain filtering
    2. Composite index (status, source, id) covering index for work queue main query
    3. Foreign key indexes on articles.candidate_link_id (most critical - 25s query!)
    4. Foreign key indexes on other high-traffic tables
    5. Index on articles table for NOT IN subquery optimization
    """
    
    # CRITICAL: Index for work queue main query (status + source filter + LEFT JOIN)
    # This query runs every few seconds and was taking 4-25 seconds
    # Benefits: Filters candidate_links by status='article' AND source='domain'
    # Before: Sequential scan through all candidate_links
    # After: Index seek directly to matching rows
    op.create_index(
        'ix_candidate_links_status_source',
        'candidate_links',
        ['status', 'source'],
        unique=False
    )
    
    # Composite covering index for work queue query optimization
    # Includes 'id' to allow index-only scans when checking NOT IN articles
    op.create_index(
        'ix_candidate_links_status_source_id',
        'candidate_links',
        ['status', 'source', 'id'],
        unique=False
    )
    
    # CRITICAL: Foreign key index on articles.candidate_link_id
    # The domain grouping query does:
    # cl.id NOT IN (SELECT candidate_link_id FROM articles)
    # This was causing a 25 SECOND sequential scan of 43k article rows!
    # With this index, the NOT IN becomes an index seek
    op.create_index(
        'ix_articles_candidate_link_id',
        'articles',
        ['candidate_link_id'],
        unique=False
    )
    
    # Foreign key indexes on other high-traffic tables
    # These prevent sequential scans when doing JOINs
    
    # locations table - JOINs to articles frequently in reporting queries
    op.create_index(
        'ix_locations_article_id',
        'locations',
        ['article_id'],
        unique=False
    )
    
    # ml_results table - JOINs to articles and jobs
    op.create_index(
        'ix_ml_results_article_id',
        'ml_results',
        ['article_id'],
        unique=False
    )
    
    op.create_index(
        'ix_ml_results_job_id',
        'ml_results',
        ['job_id'],
        unique=False
    )
    
    # background_processes table - self-referential FK for process trees
    op.create_index(
        'ix_background_processes_parent_process_id',
        'background_processes',
        ['parent_process_id'],
        unique=False
    )
    
    # Content cleaning telemetry tables - high volume, frequent JOINs
    op.create_index(
        'ix_content_cleaning_locality_events_telemetry_id',
        'content_cleaning_locality_events',
        ['telemetry_id'],
        unique=False
    )
    
    op.create_index(
        'ix_content_cleaning_wire_events_telemetry_id',
        'content_cleaning_wire_events',
        ['telemetry_id'],
        unique=False
    )
    
    # dataset_deltas table - versioning queries
    op.create_index(
        'ix_dataset_deltas_dataset_version_id',
        'dataset_deltas',
        ['dataset_version_id'],
        unique=False
    )


def downgrade() -> None:
    """Remove performance indexes."""
    
    # Drop in reverse order
    op.drop_index(
        'ix_dataset_deltas_dataset_version_id',
        table_name='dataset_deltas'
    )
    op.drop_index(
        'ix_content_cleaning_wire_events_telemetry_id',
        table_name='content_cleaning_wire_events'
    )
    op.drop_index(
        'ix_content_cleaning_locality_events_telemetry_id',
        table_name='content_cleaning_locality_events'
    )
    op.drop_index(
        'ix_background_processes_parent_process_id',
        table_name='background_processes'
    )
    op.drop_index('ix_ml_results_job_id', table_name='ml_results')
    op.drop_index('ix_ml_results_article_id', table_name='ml_results')
    op.drop_index('ix_locations_article_id', table_name='locations')
    op.drop_index(
        'ix_articles_candidate_link_id',
        table_name='articles'
    )
    op.drop_index(
        'ix_candidate_links_status_source_id',
        table_name='candidate_links'
    )
    op.drop_index(
        'ix_candidate_links_status_source',
        table_name='candidate_links'
    )
