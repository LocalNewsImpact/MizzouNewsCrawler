"""An article knows its dataset, so asking for a dataset's articles reads one index.

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-09-08

The dataset an article belongs to was recorded one table away, on the
candidate link it was extracted from. Every "articles in this dataset"
question therefore joined articles to candidate_links, and on the
production instance -- 1.7 GB of RAM, 128 MB of shared_buffers, against
a 286 MB articles heap and a 195 MB candidate_links heap -- that join
scanned all of candidate_links to find the dataset's links before it
could touch a single article. Datadesk measured it: the extraction
queue's count for March 2026 / Mizzou read 61,280 pages, 479 MB, and the
page runs three such counts plus the row fetch. Warm it was 0.6 seconds
a query; on a first touch the page took 11 to 18 seconds, because nothing
that size stays resident.

The article carries its dataset now. Every article has a candidate link
(164,940 of 164,940) and every link that belongs to a dataset carries
its id, so the value is exact, and the insert derives it from the link
by primary key so the two cannot disagree for any article written from
here on.

Two indexes shape the queue's filter, which is `dataset AND (published
on or after X, or undated and created on or after X)`: one for the
dated arm, one partial for the undated arm. Together they turn the
count into a bitmap over a few hundred pages.

ANALYZE at the end, on purpose. DDL does not count toward autovacuum's
modification bar, so a column added and filled by a migration has no
statistics until something else happens to cross it -- text_length went
a day without any, and the planner costed the queue's ORDER BY on
nothing. A migration that adds a column an index will be used on ends
with ANALYZE.
"""

import sqlalchemy as sa
from alembic import op

revision = "t5u6v7w8x9y0"
down_revision = "s4t5u6v7w8x9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The fill writes a new version of every article row. Two minutes is
    # the session default and would not cover it on this instance.
    op.execute("SET statement_timeout = '30min'")
    op.add_column("articles", sa.Column("dataset_id", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE articles a
           SET dataset_id = cl.dataset_id
          FROM candidate_links cl
         WHERE cl.id = a.candidate_link_id
           AND cl.dataset_id IS NOT NULL
        """
    )
    op.create_index(
        "ix_articles_dataset_published",
        "articles",
        ["dataset_id", sa.text("publish_date DESC NULLS LAST"), sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_articles_dataset_undated",
        "articles",
        ["dataset_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("publish_date IS NULL"),
    )
    op.execute("ANALYZE articles")


def downgrade() -> None:
    op.drop_index("ix_articles_dataset_undated", table_name="articles")
    op.drop_index("ix_articles_dataset_published", table_name="articles")
    op.drop_column("articles", "dataset_id")
