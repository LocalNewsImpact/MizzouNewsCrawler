"""Add router_proxy column to extraction_telemetry_v2.

proxy_url records the raw session proxy string and was observed to be NULL on
most rows even when the shared proxy_router had assigned mizzou_squid, so a
per-article export could not answer which physical proxy served a request.
router_proxy persists the router's own decision (home_squid / mizzou_squid).

Revision ID: e7a1c2b3d4f5
Revises: d5f1a2b3c4e6
Create Date: 2026-07-26

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7a1c2b3d4f5"
down_revision: Union[str, None] = "d5f1a2b3c4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add router_proxy column and an index for per-proxy aggregation."""
    op.add_column(
        "extraction_telemetry_v2",
        sa.Column("router_proxy", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_extraction_telemetry_v2_router_proxy",
        "extraction_telemetry_v2",
        ["router_proxy"],
        unique=False,
    )


def downgrade() -> None:
    """Remove router_proxy column."""
    op.drop_index(
        "ix_extraction_telemetry_v2_router_proxy",
        table_name="extraction_telemetry_v2",
    )
    op.drop_column("extraction_telemetry_v2", "router_proxy")
