"""A decision can go stale.

A decided byline is never asked about again. That is deliberate -- a queue
that keeps re-asking settled questions is a queue nobody finishes -- and it
assumes the answer stays true.

It does not. The answer depends on facts outside the byline:

  `cross_owner` fires when a name appears under owners that are not one
  company. It is read through `owner_groups` and `sources.owner`, so a
  reviewer's "yes, one person" was given against the ownership we recorded
  THAT DAY. Seven NEMOnews papers were carried as seven unrelated owners
  until 2026-09-24; three more owner strings were typos. Correcting those
  changes which bylines cross ownership, and 50 decided Mizzou bylines still
  did afterwards.

  The byline STRING itself changes. `Rudi Keller Missouri Independent` and
  `Rudi Keller` were two rows to decide separately; once the masthead comes
  off the capture they are one person, and the decision made about either
  was made about a string that no longer exists.

WITHOUT THIS THE ONLY WAY BACK IS DELETION. Clearing
`byline_normalizations` re-opens the question and destroys the answer,
including `applied_at` -- the record that the decision was written onto
`articles.author` -- so a re-review starts from nothing and cannot tell
which rows the corpus already carries.

So a decision is marked stale instead. The row keeps its answer, who gave
it and when it was applied; `stale_at` says it needs asking again and
`stale_reason` says why, which is what a reviewer needs in order to answer
faster the second time rather than slower.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""

import sqlalchemy as sa
from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "byline_normalizations",
        sa.Column("stale_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "byline_normalizations",
        sa.Column("stale_reason", sa.Text(), nullable=True),
    )
    # The queue reads "which of this dataset's decisions need asking again"
    # on every refresh, and almost none of them do.
    op.create_index(
        "ix_byline_normalizations_stale",
        "byline_normalizations",
        ["dataset_id", "stale_at"],
        postgresql_where=sa.text("stale_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_byline_normalizations_stale", table_name="byline_normalizations"
    )
    op.drop_column("byline_normalizations", "stale_reason")
    op.drop_column("byline_normalizations", "stale_at")
