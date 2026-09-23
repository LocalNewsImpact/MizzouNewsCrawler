"""A spelling cluster is one review.

"Bruce E Stidham" and "Bruce E. Stidham" were two candidates, each naming the
other as a variant, and a reviewer had to answer the same person twice and hope
the two answers agreed. The cluster is now the row, and `group` carries every
spelling with its own article count and hosts -- which spelling is correct is a
judgement made by comparing those.

`group` is quoted everywhere it appears: GROUP is a reserved word in SQL.

Nothing is migrated. The table is a queue the crawler recomputes wholesale every
night, so the rows written before this are replaced by the next refresh.

Revision ID: 3a9c5e7b2f14
Revises: 2f8b4c1e6a37
"""

import sqlalchemy as sa
from alembic import op

revision = "3a9c5e7b2f14"
down_revision = "2f8b4c1e6a37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "byline_review_candidates",
        sa.Column("group", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("byline_review_candidates", "group")
