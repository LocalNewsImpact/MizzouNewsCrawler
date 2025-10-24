"""add_remaining_telemetry_tables

Revision ID: a9957c3054a4
Revises: zzzz_resync_extraction_telemetry_sequence
Create Date: 2025-10-05 15:22:57.549520

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9957c3054a4'
down_revision: Union[str, Sequence[str], None] = 'zzzz_resync_extraction_telemetry_sequence'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add remaining telemetry tables."""
    
    # Add missing index on byline_cleaning_telemetry.created_at
    # (table already created in migration e3114395bcc4)
    op.create_index(op.f('ix_byline_cleaning_telemetry_created_at'), 'byline_cleaning_telemetry', ['created_at'], unique=False)
    
    # Content cleaning sessions table
    op.create_table(
        'content_cleaning_sessions',
        sa.Column('telemetry_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('domain', sa.String(), nullable=True),
        sa.Column('article_count', sa.Integer(), nullable=True),
        sa.Column('min_occurrences', sa.Integer(), nullable=True),
        sa.Column('min_boundary_score', sa.Float(), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=True),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('processing_time_ms', sa.Float(), nullable=True),
        sa.Column('rough_candidates_found', sa.Integer(), nullable=True),
        sa.Column('segments_detected', sa.Integer(), nullable=True),
        sa.Column('total_removable_chars', sa.Integer(), nullable=True),
        sa.Column('removal_percentage', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('telemetry_id')
    )
    op.create_index(op.f('ix_content_cleaning_sessions_domain'), 'content_cleaning_sessions', ['domain'], unique=False)
    op.create_index(op.f('ix_content_cleaning_sessions_created_at'), 'content_cleaning_sessions', ['created_at'], unique=False)
    
    # Content cleaning segments table
    op.create_table(
        'content_cleaning_segments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('telemetry_id', sa.String(), nullable=False),
        sa.Column('detection_number', sa.Integer(), nullable=True),
        sa.Column('segment_text', sa.Text(), nullable=True),
        sa.Column('segment_text_hash', sa.Integer(), nullable=True),
        sa.Column('boundary_score', sa.Float(), nullable=True),
        sa.Column('occurrences', sa.Integer(), nullable=True),
        sa.Column('pattern_type', sa.String(), nullable=True),
        sa.Column('position_consistency', sa.Float(), nullable=True),
        sa.Column('segment_length', sa.Integer(), nullable=True),
        sa.Column('affected_article_count', sa.Integer(), nullable=True),
        sa.Column('was_removed', sa.Boolean(), nullable=True),
        sa.Column('removal_reason', sa.String(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('article_ids_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['telemetry_id'], ['content_cleaning_sessions.telemetry_id'], )
    )
    op.create_index(op.f('ix_content_cleaning_segments_telemetry_id'), 'content_cleaning_segments', ['telemetry_id'], unique=False)
    
    # Content cleaning wire events table
    op.create_table(
        'content_cleaning_wire_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('telemetry_id', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('domain', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('detection_method', sa.String(), nullable=True),
        sa.Column('detection_stage', sa.String(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('pattern_text', sa.Text(), nullable=True),
        sa.Column('pattern_text_hash', sa.Integer(), nullable=True),
        sa.Column('article_ids_json', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['telemetry_id'], ['content_cleaning_sessions.telemetry_id'], )
    )
    op.create_index(op.f('ix_content_cleaning_wire_events_telemetry_id'), 'content_cleaning_wire_events', ['telemetry_id'], unique=False)
    op.create_index(op.f('ix_content_cleaning_wire_events_domain'), 'content_cleaning_wire_events', ['domain'], unique=False)
    
    # Content cleaning locality events table
    op.create_table(
        'content_cleaning_locality_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('telemetry_id', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('domain', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('detection_method', sa.String(), nullable=True),
        sa.Column('article_id', sa.String(), nullable=True),
        sa.Column('is_local', sa.Boolean(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('raw_score', sa.Float(), nullable=True),
        sa.Column('threshold', sa.Float(), nullable=True),
        sa.Column('signals_json', sa.Text(), nullable=True),
        sa.Column('locality_json', sa.Text(), nullable=True),
        sa.Column('source_context_json', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['telemetry_id'], ['content_cleaning_sessions.telemetry_id'], )
    )
    op.create_index(op.f('ix_content_cleaning_locality_events_telemetry_id'), 'content_cleaning_locality_events', ['telemetry_id'], unique=False)
    
    # Persistent boilerplate patterns table
    op.create_table(
        'persistent_boilerplate_patterns',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('pattern_text', sa.Text(), nullable=False),
        sa.Column('pattern_text_hash', sa.Integer(), nullable=False),
        sa.Column('pattern_type', sa.String(), nullable=True),
        sa.Column('occurrence_count', sa.Integer(), nullable=True),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_detected', sa.DateTime(), nullable=True),
        sa.Column('segment_length', sa.Integer(), nullable=True),
        sa.Column('boundary_score', sa.Float(), nullable=True),
        sa.Column('position_consistency', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_persistent_boilerplate_patterns_domain'), 'persistent_boilerplate_patterns', ['domain'], unique=False)
    op.create_index(op.f('ix_persistent_boilerplate_patterns_pattern_text_hash'), 'persistent_boilerplate_patterns', ['pattern_text_hash'], unique=False)
    
    # Content type detection telemetry table
    op.create_table(
        'content_type_detection_telemetry',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('operation_id', sa.String(), nullable=False),
        sa.Column('article_id', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('host', sa.String(), nullable=True),
        sa.Column('http_content_type', sa.String(), nullable=True),
        sa.Column('detected_type', sa.String(), nullable=False),
        sa.Column('detection_method', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('file_extension', sa.String(), nullable=True),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('byte_signature', sa.String(), nullable=True),
        sa.Column('content_sample', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_content_type_detection_telemetry_article_id'), 'content_type_detection_telemetry', ['article_id'], unique=False)
    op.create_index(op.f('ix_content_type_detection_telemetry_detected_type'), 'content_type_detection_telemetry', ['detected_type'], unique=False)
    op.create_index(op.f('ix_content_type_detection_telemetry_created_at'), 'content_type_detection_telemetry', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema - remove telemetry tables."""
    op.drop_index(op.f('ix_content_type_detection_telemetry_created_at'), table_name='content_type_detection_telemetry')
    op.drop_index(op.f('ix_content_type_detection_telemetry_detected_type'), table_name='content_type_detection_telemetry')
    op.drop_index(op.f('ix_content_type_detection_telemetry_article_id'), table_name='content_type_detection_telemetry')
    op.drop_table('content_type_detection_telemetry')
    
    op.drop_index(op.f('ix_persistent_boilerplate_patterns_pattern_text_hash'), table_name='persistent_boilerplate_patterns')
    op.drop_index(op.f('ix_persistent_boilerplate_patterns_domain'), table_name='persistent_boilerplate_patterns')
    op.drop_table('persistent_boilerplate_patterns')
    
    op.drop_index(op.f('ix_content_cleaning_locality_events_telemetry_id'), table_name='content_cleaning_locality_events')
    op.drop_table('content_cleaning_locality_events')
    
    op.drop_index(op.f('ix_content_cleaning_wire_events_domain'), table_name='content_cleaning_wire_events')
    op.drop_index(op.f('ix_content_cleaning_wire_events_telemetry_id'), table_name='content_cleaning_wire_events')
    op.drop_table('content_cleaning_wire_events')
    
    op.drop_index(op.f('ix_content_cleaning_segments_telemetry_id'), table_name='content_cleaning_segments')
    op.drop_table('content_cleaning_segments')
    
    op.drop_index(op.f('ix_content_cleaning_sessions_created_at'), table_name='content_cleaning_sessions')
    op.drop_index(op.f('ix_content_cleaning_sessions_domain'), table_name='content_cleaning_sessions')
    op.drop_table('content_cleaning_sessions')
    
    # Drop only the index we added (tables are handled by migration e3114395bcc4)
    op.drop_index(op.f('ix_byline_cleaning_telemetry_created_at'), table_name='byline_cleaning_telemetry')
