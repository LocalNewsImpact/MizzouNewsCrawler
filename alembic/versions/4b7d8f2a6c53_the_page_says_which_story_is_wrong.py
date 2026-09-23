"""The page says which story is wrong.

A byline under unrelated owners is legitimate for a stringer and for papers
sharing copy, and nothing on the row separated that from a misattribution --
except the line the paper printed, where it printed one.

`mismatches` holds the stories whose page names somebody else:
`[{article_id, url, title, host, printed}]`, so the console can offer the printed
name as a one-click correction instead of asking somebody to retype it.

It answers rarely, and that is its honest shape: of the 1,202 stories behind
Mizzou's 175 candidates, ONE disagrees -- the unterrifieddemocrat.com school board
story credited to a KY3 reporter, which reads "By Neal A. Johnson, UD Editor".

Nothing is migrated. The table is a queue the crawler recomputes wholesale every
night, so the rows written before this are replaced by the next refresh.

Revision ID: 4b7d8f2a6c53
Revises: 3a9c5e7b2f14
"""

import sqlalchemy as sa
from alembic import op

revision = "4b7d8f2a6c53"
down_revision = "3a9c5e7b2f14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "byline_review_candidates",
        sa.Column("mismatches", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("byline_review_candidates", "mismatches")
