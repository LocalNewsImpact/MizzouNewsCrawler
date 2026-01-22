"""Merge AMP bypass and other migrations

Revision ID: 1af3ad9422f5
Revises: b1c2d3e4f5a6, c7f01f4f73da
Create Date: 2026-01-22 10:00:50.625478

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '1af3ad9422f5'
down_revision: Union[str, Sequence[str], None] = ('b1c2d3e4f5a6', 'c7f01f4f73da')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
