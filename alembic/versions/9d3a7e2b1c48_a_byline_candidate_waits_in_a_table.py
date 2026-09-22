"""A byline candidate waits in a table.

The signals are computed in `byline_review`, and the person who acts on them
works in datadesk -- a different repository, a different process, reading the
same database. Three ways to join those: duplicate the rules there, publish them
in a shared package, or compute them here and leave the answer where the queue
can read it.

This is the third. The rules stay in one place, datadesk renders rows and writes
decisions, and a refresh is a batch job rather than 7,921 strings scored inside
a web request.

One row per (dataset, raw byline) that needs review, replaced wholesale on each
refresh: a candidate is a statement about the corpus as it is now, and a decided
or repaired string simply stops being written.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9d3a7e2b1c48"
down_revision: Union[str, Sequence[str], None] = "8c2f6d0b5e31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "byline_review_candidates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dataset_id", sa.String(), nullable=False, index=True),
        sa.Column("raw_byline", sa.Text(), nullable=False),
        #: The worst thing about this string, which is what orders the queue.
        sa.Column("signal", sa.String(length=32), nullable=False, index=True),
        sa.Column("signal_label", sa.Text(), nullable=False),
        #: Every signal it shows, so a row can say more than its headline.
        sa.Column("signals", sa.JSON(), nullable=False),
        #: What the splitter reads it as: the names, in order.
        sa.Column("proposed", sa.JSON(), nullable=False),
        #: Other spellings of the same name, and how each differs -- "case
        #: only", "spelling" -- because two of them can look identical.
        sa.Column("variants", sa.JSON(), nullable=False),
        sa.Column("differs_by", sa.JSON(), nullable=False),
        sa.Column("articles", sa.Integer(), nullable=False),
        sa.Column("hosts", sa.JSON(), nullable=False),
        sa.Column("owners", sa.JSON(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_unique_constraint(
        "uq_byline_review_candidates_dataset_raw",
        "byline_review_candidates",
        ["dataset_id", "raw_byline"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_byline_review_candidates_dataset_raw",
        "byline_review_candidates",
        type_="unique",
    )
    op.drop_table("byline_review_candidates")
