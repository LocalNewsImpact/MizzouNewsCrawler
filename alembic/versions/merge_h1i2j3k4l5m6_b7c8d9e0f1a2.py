"""merge heads h1i2j3k4l5m6 and b7c8d9e0f1a2

Revision ID: c3d4e5f6a7b8
Revises: h1i2j3k4l5m6, b7c8d9e0f1a2
Create Date: 2025-11-09 00:00:00.000000

This merge revision unifies two parallel heads that diverged after adding
content type detection columns (h1i2j3k4l5m6) and typed RSS state columns
(b7c8d9e0f1a2). No schema changes are performed; it records lineage so
`alembic upgrade head` no longer fails with multiple heads.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = ("h1i2j3k4l5m6", "b7c8d9e0f1a2")
branch_labels = None
depends_on = None


def upgrade() -> None:  # pragma: no cover
    # Merge-only revision; no operational changes.
    return


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Downgrade not supported for merge revision c3d4e5f6a7b8")
