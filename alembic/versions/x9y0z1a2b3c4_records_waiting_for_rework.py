"""Which records need carrying, said once and read by everything.

Housekeeping exists to carry the handful of records a review decision
rewound through the rest of the pipeline. Every pipeline stage selects by
STATUS, and a rewound record shares its status with the whole backlog --
so a stage told nothing takes everything. A housekeeping run began
extracting 4,802 links when the dispositions accounted for 45.

The records have to be named, and the name has to live somewhere both
sides can read.

WHY A TABLE AND NOT THE ALTERNATIVES.

Not a file passed between pods: that is working state, and the moment a
run dies halfway the file and the database disagree about what is left.

Not a timestamp: neither `articles` nor `candidate_links` carries an
`updated_at`, so nothing marks a status change, and adding one would say
"this row moved" without saying why or whether anything still owes it
work.

Not the console's audit log, where the reconciler already records what it
moved: those rows are in another database, and the crawler having
credentials for the console's tables to read one column is a coupling
that outlives the reason for it.

So: a row per record that owes work, written by whoever rewound it, and
closed when the work is done. It answers "what is left" directly, which
is the question every stage and every operator actually asks.

Revision ID: x9y0z1a2b3c4
Revises: w8x9y0z1a2b3
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "x9y0z1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "w8x9y0z1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_rework",
        sa.Column("id", sa.Integer, primary_key=True),
        # Which table the id belongs to. A link owes a fetch; an article
        # owes a classification. The stages read one kind each and a
        # single column keeps them from having to know about two tables.
        sa.Column("record_type", sa.Text, nullable=False),
        sa.Column("record_id", sa.Text, nullable=False),
        # The stage that owes the work: 'extract', 'classify', 'enrich'.
        # Named rather than inferred from the status, because a status is
        # where a record IS and this is what it still needs.
        sa.Column("stage", sa.Text, nullable=False),
        # Why, in the words of the decision that caused it. This is what
        # somebody reads when a row has been waiting a week.
        sa.Column("reason", sa.Text),
        sa.Column("requested_by", sa.Text, nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Closed rather than deleted: "what did housekeeping do last week"
        # is a question, and a table that empties itself cannot answer it.
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text),
    )
    # What every stage asks: what is still owed, oldest first.
    op.create_index(
        "ix_pipeline_rework_outstanding",
        "pipeline_rework",
        ["stage", "requested_at"],
        postgresql_where=sa.text("done_at IS NULL"),
    )
    # One outstanding request per record per stage. Asking twice is the
    # same ask, and two rows would extract the same link twice.
    op.create_index(
        "uq_pipeline_rework_outstanding",
        "pipeline_rework",
        ["record_type", "record_id", "stage"],
        unique=True,
        postgresql_where=sa.text("done_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pipeline_rework_outstanding", table_name="pipeline_rework")
    op.drop_index("ix_pipeline_rework_outstanding", table_name="pipeline_rework")
    op.drop_table("pipeline_rework")
