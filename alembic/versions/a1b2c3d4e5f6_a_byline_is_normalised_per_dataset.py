"""A byline is normalised per dataset.

`articles.author` is what a parser made of a page, and across a dataset it holds
the same person under several spellings, several people in one string, job
titles, publication suffixes and, from a September 2025 defect, Python list
literals: 1,716 Mizzou articles read `["Stanley Schwartz"]` and 188 read `[]`.
A report of "unique local bylines" over that counts spellings, not people.

This table is the decision: for ONE dataset, what a raw byline string actually
is. One or more canonical people, or nothing at all when the string names no
person ("Admin", "ABC 17 News Team").

PER DATASET, deliberately. The same string can be a person in one corpus and a
desk in another, and a reviewer works one dataset at a time -- so a decision
carries the dataset it was made in and reaches nothing else.

The table does not replace the article's byline: applying a decision rewrites
`articles.author` for that dataset's matching rows, so the permanent record
carries the corrected name. It is kept because extraction can write the raw
form again, and because the decision is the audit -- who decided, when, and on
how many rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "byline_normalizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("dataset_id", sa.String(), nullable=False, index=True),
        # The string exactly as the article carried it, which is what a later
        # extraction would write again and what the queue matches on.
        sa.Column("raw_byline", sa.Text(), nullable=False),
        # The people the string names, in order. An empty list is a decision
        # too: the string names nobody, and the byline is cleared.
        sa.Column("canonical_names", sa.JSON(), nullable=False),
        # `fix`, `accept` (the raw string is already right) or `drop` (names
        # nobody). Kept apart from the names so "accepted as is" and "fixed to
        # the same thing" do not read alike.
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # When the decision last reached `articles.author`, and how many rows
        # it wrote. Null means decided but not yet applied.
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("articles_updated", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_byline_normalizations_dataset_raw",
        "byline_normalizations",
        ["dataset_id", "raw_byline"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_byline_normalizations_dataset_raw",
        "byline_normalizations",
        type_="unique",
    )
    op.drop_table("byline_normalizations")
