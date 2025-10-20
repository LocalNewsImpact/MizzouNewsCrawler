"""add_proxy_and_alternative_columns_to_extraction_telemetry

Revision ID: c22022d6d3ec
Revises: fe5057825d26
Create Date: 2025-10-18 20:07:37.323186

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c22022d6d3ec'
down_revision: Union[str, Sequence[str], None] = 'fe5057825d26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add proxy columns to extraction_telemetry_v2.
    
    Note: alternative_extractions already exists from migration a1b2c3d4e5f6,
    so we don't add it again.
    """
    # Add proxy-related columns
    op.add_column('extraction_telemetry_v2',
                  sa.Column('proxy_used', sa.Integer(), nullable=True))
    op.add_column('extraction_telemetry_v2',
                  sa.Column('proxy_url', sa.String(), nullable=True))
    op.add_column('extraction_telemetry_v2',
                  sa.Column('proxy_authenticated', sa.Integer(), nullable=True))
    op.add_column('extraction_telemetry_v2',
                  sa.Column('proxy_status', sa.Integer(), nullable=True))
    op.add_column('extraction_telemetry_v2',
                  sa.Column('proxy_error', sa.String(), nullable=True))

    # Note: alternative_extractions column already exists from migration a1b2c3d4e5f6
    # We don't add it again to avoid duplicate column errors


def downgrade() -> None:
    """Remove proxy columns from extraction_telemetry_v2.
    
    Note: We don't drop alternative_extractions as it was created in
    migration a1b2c3d4e5f6, not this migration.
    """
    # Note: alternative_extractions was created in migration a1b2c3d4e5f6, not here
    # So we don't drop it in this downgrade
    op.drop_column('extraction_telemetry_v2', 'proxy_error')
    op.drop_column('extraction_telemetry_v2', 'proxy_status')
    op.drop_column('extraction_telemetry_v2', 'proxy_authenticated')
    op.drop_column('extraction_telemetry_v2', 'proxy_url')
    op.drop_column('extraction_telemetry_v2', 'proxy_used')
