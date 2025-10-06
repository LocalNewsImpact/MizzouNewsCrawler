"""set default on gazetteer.created_at

Revision ID: fe12ab34cd56
Revises: e3114395bcc4
Create Date: 2025-10-06 13:18:00.000000
"""

from typing import Sequence, Union

from alembic import op  # type: ignore
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe12ab34cd56'
down_revision: Union[str, None] = 'e3114395bcc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Set server default to NOW() to avoid NOT NULL violations on direct inserts
    op.alter_column(
        'gazetteer',
        'created_at',
        existing_type=sa.DateTime(),
        server_default=sa.text('NOW()'),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Remove server default
    op.alter_column(
        'gazetteer',
        'created_at',
        existing_type=sa.DateTime(),
        server_default=None,
        existing_nullable=False,
    )
