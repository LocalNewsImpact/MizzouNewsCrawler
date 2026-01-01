"""add driver metrics column to extraction telemetry

Revision ID: c7f01f4f73da
Revises: 1da1c56c201f
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7f01f4f73da"
down_revision: Union[str, Sequence[str], None] = "1da1c56c201f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add driver_metrics column for Selenium/proxy telemetry."""

    op.add_column(
        "extraction_telemetry_v2",
        sa.Column("driver_metrics", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove driver_metrics column."""

    op.drop_column("extraction_telemetry_v2", "driver_metrics")
