"""Merge the backfield enrichment chain with the article sort index.

Both descend from e7a1c2b3d4f5 and neither knows about the other:

    e7a1c2b3d4f5
    |-- a7c3f9e2d481                     articles publish_date sort index
    `-- f8b2d3c4e5a6 -> a9c3d4e5f6b7     backfield enrichment tables,
        -> b1d4e5f6a7c8 -> c2e5f6a7b8d9  then the geoid ladder
        -> d3f6a7b8c9e0 -> e4a7b8c9d0f1

`alembic upgrade head` refuses to run against two heads, so this joins them.
No schema change of its own.

A note for whoever reads this after an incident, because production's
recorded revision has been wrong twice and the reason matters:

Both branches were applied to the production database before either was
merged. On 2026-08-23 alembic_version held e4a7b8c9d0f1 -- this branch's
tip, applied from an unmerged branch -- while main's chain through
e7a1c2b3d4f5 was also physically present. Reading only the merged history,
e4a7b8c9d0f1 looked like a revision that had never existed, and the pointer
was moved to e7a1c2b3d4f5. That discarded the record of this chain having
run. The index from a7c3f9e2d481 was then applied by hand and is also
unrecorded.

So the schema is ahead of the pointer in both directions, and the
migrations here are not written to be re-runnable: `op.add_column` and
`op.create_table` raise on something that already exists. Stamping is
required rather than upgrading -- see the pull request for the exact
command and the columns it was verified against.

Revision ID: 9e4c7a1b2d8f
Revises: e4a7b8c9d0f1, a7c3f9e2d481
Create Date: 2026-08-23
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "9e4c7a1b2d8f"
down_revision: Union[str, Sequence[str], None] = ("e4a7b8c9d0f1", "a7c3f9e2d481")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Nothing to do. This exists to give the two branches one head."""


def downgrade() -> None:
    """Nothing to undo; splitting the head again is not a schema change."""
