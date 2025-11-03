"""Add bot sensitivity tracking to sources table

Revision ID: fe5057825d26
Revises: 1c15007392b3
Create Date: 2025-10-12 14:00:00.000000

Adds bot sensitivity tracking to enable adaptive crawling behavior based on
bot detection encounters. Includes sensitivity rating, encounter tracking,
and metadata storage.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'fe5057825d26'
down_revision = '1c15007392b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add bot sensitivity columns to sources table."""
    
    # Check if column already exists
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('sources')]
    
    if 'bot_sensitivity' in columns:
        # Column already exists, skip
        return
    
    # Check if we're using SQLite (for batch mode)
    is_sqlite = bind.dialect.name == 'sqlite'
    
    if is_sqlite:
        # SQLite requires batch mode for constraints
        with op.batch_alter_table('sources', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'bot_sensitivity',
                    sa.Integer(),
                    nullable=True,
                    comment=(
                        'Bot sensitivity rating (1-10 scale): '
                        '1=permissive, 10=extremely sensitive'
                    )
                )
            )
        
        # Set default value for existing rows
        op.execute(
            "UPDATE sources SET bot_sensitivity = 5 WHERE bot_sensitivity IS NULL"
        )
        
        # Add check constraint in batch mode
        with op.batch_alter_table('sources', schema=None) as batch_op:
            batch_op.create_check_constraint(
                'ck_sources_bot_sensitivity_range',
                'bot_sensitivity >= 1 AND bot_sensitivity <= 10'
            )
    else:
        # PostgreSQL can do direct ALTER TABLE
        op.add_column(
            'sources',
            sa.Column(
                'bot_sensitivity',
                sa.Integer(),
                nullable=True,
                comment=(
                    'Bot sensitivity rating (1-10 scale): '
                    '1=permissive, 10=extremely sensitive'
                )
            )
        )
        
        # Set default value for existing rows
        op.execute(
            "UPDATE sources SET bot_sensitivity = 5 WHERE bot_sensitivity IS NULL"
        )
        
        # Add check constraint
        op.create_check_constraint(
            'ck_sources_bot_sensitivity_range',
            'sources',
            'bot_sensitivity >= 1 AND bot_sensitivity <= 10'
        )
    
    # Add timestamp for when sensitivity was last updated
    op.add_column(
        'sources',
        sa.Column(
            'bot_sensitivity_updated_at',
            sa.DateTime(),
            nullable=True,
            comment='When bot sensitivity was last adjusted'
        )
    )
    
    # Add counter for bot detection encounters
    op.add_column(
        'sources',
        sa.Column(
            'bot_encounters',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of bot detection events encountered'
        )
    )
    
    # Add timestamp of last bot detection
    op.add_column(
        'sources',
        sa.Column(
            'last_bot_detection_at',
            sa.DateTime(),
            nullable=True,
            comment='When last bot detection event occurred'
        )
    )
    
    # Add JSON metadata for bot detection patterns and history
    # Use JSON for cross-database compatibility (SQLite doesn't support JSONB)
    json_type = postgresql.JSONB(astext_type=sa.Text()) if not is_sqlite else sa.JSON()
    op.add_column(
        'sources',
        sa.Column(
            'bot_detection_metadata',
            json_type,
            nullable=True,
            comment='Bot detection patterns, indicators, and adjustment history'
        )
    )
    
    # Create index on bot_sensitivity for querying by sensitivity level
    op.create_index(
        'ix_sources_bot_sensitivity',
        'sources',
        ['bot_sensitivity']
    )
    
    # Create index for tracking recent bot encounters
    op.create_index(
        'ix_sources_last_bot_detection',
        'sources',
        ['last_bot_detection_at'],
        postgresql_where=sa.text('last_bot_detection_at IS NOT NULL')
    )
    
    # Create optional bot_detection_events table for detailed tracking
    op.create_table(
        'bot_detection_events',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column(
            'source_id',
            sa.String(),
            sa.ForeignKey('sources.id'),
            nullable=False,
            index=True
        ),
        sa.Column('host', sa.String(), nullable=False, index=True),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column(
            'event_type',
            sa.String(),
            nullable=False,
            index=True,
            comment="'403_forbidden', 'captcha', 'rate_limit', 'timeout'"
        ),
        sa.Column('http_status_code', sa.Integer(), nullable=True),
        sa.Column(
            'detection_method',
            sa.String(),
            nullable=True,
            comment="'http_status', 'response_body', 'headers'"
        ),
        sa.Column(
            'response_indicators',
            json_type,  # Same JSON type as defined earlier
            nullable=True,
            comment='Detection signals found in response'
        ),
        sa.Column('previous_sensitivity', sa.Integer(), nullable=True),
        sa.Column('new_sensitivity', sa.Integer(), nullable=True),
        sa.Column('adjustment_reason', sa.Text(), nullable=True),
        sa.Column(
            'detected_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP')
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP')
        ),
        comment='Detailed bot detection event tracking for analysis'
    )
    
    # Indexes for bot_detection_events
    op.create_index(
        'ix_bot_events_source_detected',
        'bot_detection_events',
        ['source_id', sa.text('detected_at DESC')]
    )
    
    op.create_index(
        'ix_bot_events_host_detected',
        'bot_detection_events',
        ['host', sa.text('detected_at DESC')]
    )


def downgrade() -> None:
    """Remove bot sensitivity columns from sources table."""
    
    # Drop bot_detection_events table
    op.drop_index('ix_bot_events_host_detected', table_name='bot_detection_events')
    op.drop_index('ix_bot_events_source_detected', table_name='bot_detection_events')
    op.drop_table('bot_detection_events')
    
    # Drop indexes from sources
    op.drop_index('ix_sources_last_bot_detection', table_name='sources')
    op.drop_index('ix_sources_bot_sensitivity', table_name='sources')
    
    # Check if we're using SQLite (for batch mode)
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'
    
    if is_sqlite:
        # SQLite requires batch mode for constraint drops
        with op.batch_alter_table('sources', schema=None) as batch_op:
            batch_op.drop_column('bot_detection_metadata')
            batch_op.drop_column('last_bot_detection_at')
            batch_op.drop_column('bot_encounters')
            batch_op.drop_column('bot_sensitivity_updated_at')
            batch_op.drop_constraint(
                'ck_sources_bot_sensitivity_range',
                type_='check'
            )
            batch_op.drop_column('bot_sensitivity')
    else:
        # PostgreSQL can do direct ALTER TABLE
        op.drop_column('sources', 'bot_detection_metadata')
        op.drop_column('sources', 'last_bot_detection_at')
        op.drop_column('sources', 'bot_encounters')
        op.drop_column('sources', 'bot_sensitivity_updated_at')
        op.drop_constraint(
            'ck_sources_bot_sensitivity_range',
            'sources',
            type_='check'
        )
        op.drop_column('sources', 'bot_sensitivity')
