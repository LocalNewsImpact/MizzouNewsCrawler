"""Add created_at column to datasets

The Dataset model has long declared a ``created_at`` column, but no migration
ever added it to the ``datasets`` table (the table was created without it in
e3114395bcc4 and only ``cron_enabled`` was backfilled since). This drift means
``alembic upgrade head`` builds a ``datasets`` table missing ``created_at``,
so any ORM INSERT of a Dataset fails with
``column "created_at" of relation "datasets" does not exist`` — which also
poisons the surrounding transaction and drags integration test runs out.

Backfill existing rows with the current timestamp via a server default.

Revision ID: b2d9f4c7e1a3
Revises: f7a2b9c1d3e4
Create Date: 2026-07-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2d9f4c7e1a3"
down_revision: Union[str, Sequence[str], None] = "f7a2b9c1d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add created_at to datasets, backfilling existing rows.

    server_default=CURRENT_TIMESTAMP backfills existing rows and lets raw SQL
    INSERTs that omit created_at (used in some tests) succeed; new ORM-created
    rows still use the Python-side default from the model.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("datasets")]

    if "created_at" not in columns:
        op.add_column(
            "datasets",
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade() -> None:
    """Remove created_at column from datasets table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("datasets")]

    if "created_at" in columns:
        op.drop_column("datasets", "created_at")
