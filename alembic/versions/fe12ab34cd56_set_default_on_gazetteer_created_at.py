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
    # Set server default to NOW() / CURRENT_TIMESTAMP to avoid NOT NULL violations on direct inserts
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        # SQLite does not support ALTER COLUMN; use batch_alter_table which recreates the table safely.
        with op.batch_alter_table('gazetteer') as batch_op:
            batch_op.alter_column(
                'created_at',
                existing_type=sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            'gazetteer',
            'created_at',
            existing_type=sa.DateTime(),
            server_default=sa.text('NOW()'),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Remove server default
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('gazetteer') as batch_op:
            batch_op.alter_column(
                'created_at',
                existing_type=sa.DateTime(),
                server_default=None,
                existing_nullable=False,
            )
    else:
        op.alter_column(
            'gazetteer',
            'created_at',
            existing_type=sa.DateTime(),
            server_default=None,
            existing_nullable=False,
        )
