"""A wire copy names the newsroom it came from.

`articles.status = 'wire'` says a story is not this newsroom's reporting. It
does not say whose it is. So a wire ruling is purely SUBTRACTIVE: the copies
leave enrichment and the BigQuery export, they leave both byline reports, and
nobody is credited with the work.

Steph Quinn has 307 wire copies across 36 Missouri domains. Every one of them
is the Missouri Independent's reporting, republished. The corpus had no column
in which to say so, and "how much of this newsroom's work is carried by other
newsrooms" -- syndication, the thing a wire ruling is actually evidence of --
could not be asked at all.

ONE COLUMN, NULLABLE, ON THE COPY. A syndicated copy has exactly one origin, so
a column carries it; a join table would hold the same fact with more machinery.
It is set by the byline review when a reviewer rules the outlying newsrooms for
a byline and ticks "give syndication credit": every story ruled `wire` in that
submission takes the newsroom left at `local reporting` as its origin. Null
everywhere else, and null on a wire story nobody has claimed -- absent is not
the same as none.

IT POINTS AT `sources`, NOT `nameplates`. docs/A_NEWSROOM_BELONGS_TO_A_NETWORK.md
argues for a nameplate, because the Kansas Reflector is the home newsroom of 18
wire stories here and has no `sources` row at all. That argument holds and this
column does not answer it. What it answers is what the REVIEW UI can express: a
reviewer picks the home newsroom from the hosts carrying that byline, and every
one of those is a `sources` row by construction. A newsroom we do not crawl
never appears in the list, so the checkbox can never name one. Rolling the
Columbia Missourian's three host rows up to one newsroom is then a read-time
join through `nameplates`, once that table holds anything.

NOT BACKFILLED. 21 bylines and 92 host rulings are recoverable from
`audit_auditlogentry`, which is append-only and going nowhere. Replaying them is
a series of judgements about which newsroom is home -- for Sherman Smith the
answer is a newsroom in Kansas, and counting articles picks the wrong one -- and
that is a review, not a migration.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("syndicated_from_source_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_articles_syndicated_from_source",
        "articles",
        "sources",
        ["syndicated_from_source_id"],
        ["id"],
    )
    # The question this column exists to answer is "what did THIS newsroom
    # syndicate", which reads by origin, not by article.
    op.create_index(
        "ix_articles_syndicated_from_source_id",
        "articles",
        ["syndicated_from_source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_articles_syndicated_from_source_id", table_name="articles")
    op.drop_constraint(
        "fk_articles_syndicated_from_source", "articles", type_="foreignkey"
    )
    op.drop_column("articles", "syndicated_from_source_id")
