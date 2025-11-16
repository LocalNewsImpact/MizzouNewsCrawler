"""add_section_discovery_columns

Revision ID: 61de0fe110e1
Revises: c4d5e6f7g8h9
Create Date: 2025-11-16 12:37:48.861562

Adds section discovery infrastructure columns to sources table for enhanced
news coverage. Includes discovered_sections JSON storage, enable/disable flag,
and last updated timestamp.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '61de0fe110e1'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7g8h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add section discovery columns to sources table."""
    
    # Check if columns already exist
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('sources')]
    
    if 'section_discovery_enabled' in columns:
        # Columns already exist, skip
        return
    
    # Check if we're using SQLite (for batch mode)
    is_sqlite = bind.dialect.name == 'sqlite'
    
    if is_sqlite:
        # SQLite requires batch mode for ALTER TABLE operations
        with op.batch_alter_table('sources', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'discovered_sections',
                    sa.JSON(),
                    nullable=True,
                    comment='JSON storage for discovered section URLs'
                )
            )
            batch_op.add_column(
                sa.Column(
                    'section_discovery_enabled',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('1'),
                    comment='Enable/disable section discovery for this source'
                )
            )
            batch_op.add_column(
                sa.Column(
                    'section_last_updated',
                    sa.DateTime(),
                    nullable=True,
                    comment='Timestamp of last section discovery update'
                )
            )
    else:
        # PostgreSQL can add columns directly
        op.add_column(
            'sources',
            sa.Column(
                'discovered_sections',
                postgresql.JSON(astext_type=sa.Text()),
                nullable=True,
                comment='JSON storage for discovered section URLs'
            )
        )
        op.add_column(
            'sources',
            sa.Column(
                'section_discovery_enabled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('TRUE'),
                comment='Enable/disable section discovery for this source'
            )
        )
        op.add_column(
            'sources',
            sa.Column(
                'section_last_updated',
                sa.DateTime(),
                nullable=True,
                comment='Timestamp of last section discovery update'
            )
        )


def downgrade() -> None:
    """Remove section discovery columns from sources table."""
    
    # Check if we're using SQLite (for batch mode)
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == 'sqlite'
    
    if is_sqlite:
        with op.batch_alter_table('sources', schema=None) as batch_op:
            batch_op.drop_column('section_last_updated')
            batch_op.drop_column('section_discovery_enabled')
            batch_op.drop_column('discovered_sections')
    else:
        op.drop_column('sources', 'section_last_updated')
        op.drop_column('sources', 'section_discovery_enabled')
        op.drop_column('sources', 'discovered_sections')
