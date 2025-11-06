"""Merge heads: telemetry confidence fix and verification telemetry

Revision ID: d3e3764ec645
Revises: b8c9d0e1f2a3, g4h5i6j7k8l9
Create Date: 2025-11-06 12:04:38.549694

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'd3e3764ec645'
down_revision: Union[str, Sequence[str], None] = ('b8c9d0e1f2a3', 'g4h5i6j7k8l9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
