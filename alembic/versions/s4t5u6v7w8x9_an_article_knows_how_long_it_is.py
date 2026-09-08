"""An article knows how long it is, so nothing has to read it to find out.

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-09-07

Every question about how much text an article holds -- "is this capture
empty", "show the longest first", "how many are under 500 characters" --
was answered by reading the body. `length(coalesce(content, text,
text_excerpt))` detoasts the article, and on a queue page that asks the
question for every row of every count, that is the whole cost of the
page. Datadesk measured the extraction queue at 254 seconds against
March 2026 Mizzou's 11,833 flagged rows; the band chips alone took 16.7
seconds because they count rows BY length.

The length is a column now, and Postgres maintains it. A generated
column cannot fall out of step with the text it measures, which matters
here because four separate code paths write `content` and `text` --
extraction, two content cleaners, and the cleaning pass -- and a column
kept in sync by hand across all of them would drift the first time one
of them was edited without the other. That is the defect class this
codebase spent today on.

STORED rather than VIRTUAL so it can be indexed, and the index is what
turns "longest first" and "under 500 characters" into index scans.

The ADD COLUMN rewrites the table: 164,940 rows, 1.37 GB, computing the
length once for each. It holds an exclusive lock while it does. Every
cron is suspended as this is written, so nothing writes to `articles`
during the rewrite and readers wait rather than fail.
"""

import sqlalchemy as sa
from alembic import op

revision = "s4t5u6v7w8x9"
down_revision = "r3s4t5u6v7w8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The rewrite reads every body. Two minutes is the session default and
    # would not cover it.
    op.execute("SET statement_timeout = '30min'")
    op.execute(
        """
        ALTER TABLE articles
          ADD COLUMN text_length integer
          GENERATED ALWAYS AS (
            length(coalesce(content, text, text_excerpt, ''))
          ) STORED
        """
    )
    # Descending, because the queue asks for the longest first and the
    # planner reads a btree either way.
    op.create_index(
        "ix_articles_text_length",
        "articles",
        [sa.text("text_length DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_articles_text_length", table_name="articles")
    op.drop_column("articles", "text_length")
