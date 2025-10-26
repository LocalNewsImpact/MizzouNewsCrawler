"""Add extraction telemetry tables and site management fields

Revision ID: a1b2c3d4e5f6
Revises: e3114395bcc4
Create Date: 2025-10-05 03:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e3114395bcc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create extraction_telemetry_v2 table
    op.create_table(
        'extraction_telemetry_v2',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('operation_id', sa.String(), nullable=False),
        sa.Column('article_id', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('publisher', sa.String(), nullable=True),
        sa.Column('host', sa.String(), nullable=True),
        # Timing metrics
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('total_duration_ms', sa.Float(), nullable=True),
        # HTTP metrics
        sa.Column('http_status_code', sa.Integer(), nullable=True),
        sa.Column('http_error_type', sa.String(), nullable=True),
        sa.Column('response_size_bytes', sa.Integer(), nullable=True),
        sa.Column('response_time_ms', sa.Float(), nullable=True),
        # Method tracking
        sa.Column('methods_attempted', sa.Text(), nullable=True),
        sa.Column('successful_method', sa.String(), nullable=True),
        sa.Column('method_timings', sa.Text(), nullable=True),
        sa.Column('method_success', sa.Text(), nullable=True),
        sa.Column('method_errors', sa.Text(), nullable=True),
        # Field extraction tracking
        sa.Column('field_extraction', sa.Text(), nullable=True),
        sa.Column('extracted_fields', sa.Text(), nullable=True),
        sa.Column('final_field_attribution', sa.Text(), nullable=True),
        sa.Column('alternative_extractions', sa.Text(), nullable=True),
        # Results
        sa.Column('content_length', sa.Integer(), nullable=True),
        sa.Column('is_success', sa.Boolean(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_extraction_telemetry_v2_operation_id'), 'extraction_telemetry_v2', ['operation_id'], unique=False)
    op.create_index(op.f('ix_extraction_telemetry_v2_article_id'), 'extraction_telemetry_v2', ['article_id'], unique=False)
    op.create_index(op.f('ix_extraction_telemetry_v2_url'), 'extraction_telemetry_v2', ['url'], unique=False)
    op.create_index(op.f('ix_extraction_telemetry_v2_publisher'), 'extraction_telemetry_v2', ['publisher'], unique=False)
    op.create_index(op.f('ix_extraction_telemetry_v2_host'), 'extraction_telemetry_v2', ['host'], unique=False)
    op.create_index(op.f('ix_extraction_telemetry_v2_successful_method'), 'extraction_telemetry_v2', ['successful_method'], unique=False)
    op.create_index(op.f('ix_extraction_telemetry_v2_is_success'), 'extraction_telemetry_v2', ['is_success'], unique=False)
    op.create_index(op.f('ix_extraction_telemetry_v2_created_at'), 'extraction_telemetry_v2', ['created_at'], unique=False)

    # Create http_error_summary table
    op.create_table(
        'http_error_summary',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('host', sa.String(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('error_type', sa.String(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('first_seen', sa.DateTime(), nullable=False),
        sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_http_error_summary_host'), 'http_error_summary', ['host'], unique=False)
    op.create_index(op.f('ix_http_error_summary_status_code'), 'http_error_summary', ['status_code'], unique=False)
    op.create_index(op.f('ix_http_error_summary_last_seen'), 'http_error_summary', ['last_seen'], unique=False)

    # Add site management columns to sources table
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('paused_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('paused_reason', sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f('ix_sources_status'), ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove site management columns from sources table
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sources_status'))
        batch_op.drop_column('paused_reason')
        batch_op.drop_column('paused_at')
        batch_op.drop_column('status')

    # Drop http_error_summary table
    op.drop_index(op.f('ix_http_error_summary_last_seen'), table_name='http_error_summary')
    op.drop_index(op.f('ix_http_error_summary_status_code'), table_name='http_error_summary')
    op.drop_index(op.f('ix_http_error_summary_host'), table_name='http_error_summary')
    op.drop_table('http_error_summary')

    # Drop extraction_telemetry_v2 table
    op.drop_index(op.f('ix_extraction_telemetry_v2_created_at'), table_name='extraction_telemetry_v2')
    op.drop_index(op.f('ix_extraction_telemetry_v2_is_success'), table_name='extraction_telemetry_v2')
    op.drop_index(op.f('ix_extraction_telemetry_v2_successful_method'), table_name='extraction_telemetry_v2')
    op.drop_index(op.f('ix_extraction_telemetry_v2_host'), table_name='extraction_telemetry_v2')
    op.drop_index(op.f('ix_extraction_telemetry_v2_publisher'), table_name='extraction_telemetry_v2')
    op.drop_index(op.f('ix_extraction_telemetry_v2_url'), table_name='extraction_telemetry_v2')
    op.drop_index(op.f('ix_extraction_telemetry_v2_article_id'), table_name='extraction_telemetry_v2')
    op.drop_index(op.f('ix_extraction_telemetry_v2_operation_id'), table_name='extraction_telemetry_v2')
    op.drop_table('extraction_telemetry_v2')
