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
    """Add proxy and alternative_extractions columns to extraction_telemetry_v2."""
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

    # Add alternative_extractions column
    op.add_column('extraction_telemetry_v2',
                  sa.Column('alternative_extractions', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove proxy and alternative_extractions columns from extraction_telemetry_v2."""
    op.drop_column('extraction_telemetry_v2', 'alternative_extractions')
    op.drop_column('extraction_telemetry_v2', 'proxy_error')
    op.drop_column('extraction_telemetry_v2', 'proxy_status')
    op.drop_column('extraction_telemetry_v2', 'proxy_authenticated')
    op.drop_column('extraction_telemetry_v2', 'proxy_url')
    op.drop_column('extraction_telemetry_v2', 'proxy_used')
