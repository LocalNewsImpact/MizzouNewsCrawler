"""Add detected_type and detection_method columns to content_type_detection_telemetry

Revision ID: h1i2j3k4l5m6
Revises: d3e3764ec645
Create Date: 2025-11-07 12:00:00.000000

This migration adds the detected_type and detection_method columns to the
content_type_detection_telemetry table. These columns were added to the code
in comprehensive_telemetry.py but were missing from the database schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, Sequence[str], None] = 'd3e3764ec645'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add detected_type and detection_method columns."""
    
    # Add detected_type column
    try:
        op.add_column(
            'content_type_detection_telemetry',
            sa.Column('detected_type', sa.String(), nullable=True)
        )
    except Exception:
        # Column might already exist
        pass
    
    # Add detection_method column
    try:
        op.add_column(
            'content_type_detection_telemetry',
            sa.Column('detection_method', sa.String(), nullable=True)
        )
    except Exception:
        # Column might already exist
        pass


def downgrade() -> None:
    """Remove detected_type and detection_method columns."""
    
    try:
        op.drop_column('content_type_detection_telemetry', 'detection_method')
    except Exception:
        pass
    
    try:
        op.drop_column('content_type_detection_telemetry', 'detected_type')
    except Exception:
        pass
