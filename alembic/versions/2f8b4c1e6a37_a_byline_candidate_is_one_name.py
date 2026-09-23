"""A byline candidate is one name.

`byline_review_candidates.raw_byline` held a byline STRING, and a string can name
two people: "Alyssa Mueller, Marcus Officer" was offered as one row, which asked
an unanswerable question -- both names are correct, and a reviewer cannot accept,
fix or drop two people at once.

The row is now one name, and `sources` says which byline strings it was read out
of. Usually that is the name itself; more when the name shares a byline with a
co-author, and the reviewer needs to see that to judge what they are answering.

Nothing is migrated. The table is a queue the crawler recomputes wholesale every
night (`refresh-byline-queue`), so the rows written before this are replaced by
the next refresh rather than converted.

Revision ID: 2f8b4c1e6a37
Revises: 9d3a7e2b1c48
"""

import sqlalchemy as sa
from alembic import op

revision = "2f8b4c1e6a37"
down_revision = "9d3a7e2b1c48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "byline_review_candidates",
        sa.Column("sources", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("byline_review_candidates", "sources")
