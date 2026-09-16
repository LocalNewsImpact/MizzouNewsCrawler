"""A point records what kept it.

`grounding.grounded` accepts a place for one of two reasons: the article
names it, or the article names an institution that sits there. Both are
defensible and they are not equally strong. The first is what the story
says. The second is induction — sound, wanted, and the whole reason the
statewide gazetteer exists, but induction nonetheless.

167 of the corpus's central places rest on the second alone. A reviewer
should be able to see exactly those, and today nobody can: the reason is
computed during enrichment against the article text and then thrown away.
datadesk, which is where review happens, cannot recompute it — it has no
access to the gate and no reason to.

So the reason is recorded where it is known.

`named` and `institution` rather than a boolean, because a third reason
is plausible (a dateline naming somewhere other than the newsroom's own
city is already usable evidence) and a boolean would have to be widened
into exactly this.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "z4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "article_enrichment",
        sa.Column("point_support", sa.String(20), nullable=True),
    )
    # The review queue's question: which points rest on induction alone.
    op.create_index(
        "ix_article_enrichment_point_support",
        "article_enrichment",
        ["point_support"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_article_enrichment_point_support", table_name="article_enrichment"
    )
    op.drop_column("article_enrichment", "point_support")
