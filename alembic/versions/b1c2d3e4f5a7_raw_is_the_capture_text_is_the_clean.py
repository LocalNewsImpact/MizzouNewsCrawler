"""`raw` is the capture, `text` is the clean.

Revision ID: b1c2d3e4f5a7
Revises: z6f7a8b9c0d1
Create Date: 2026-09-19

`articles.content` held the raw capture and `articles.text` the cleaned body,
and nothing about either name said so. The model's own comments said the
reverse -- "# Core content" on the input column, "kept for compatibility" on
the one every stage is meant to read -- and three defects had already come
from that: enrichment read the raw capture in eight places while CIN read
the clean one, `text_length` measured the capture, and the cleaning pass
wrote cleaned prose back INTO the capture, which is the defect the insert
path had been fixed to stop.

Two things change here, and they are the same fix.

RENAME. `content` becomes `raw`. `text` keeps its name, because it is the
field the pipeline converges on. PostgreSQL stores dependent definitions
parsed rather than as text, so two objects follow the rename on their own
and are asserted to in tests/alembic/test_raw_is_the_capture_postgres.py:
the partial index `ix_articles_rot47_ciphertext`, whose predicate
`content LIKE '%k^Am%'` becomes `raw LIKE` -- more correct, since ROT47
ciphertext is a property of the capture -- and the eight column-level
grants (datadesk_rw, datadesk_ro, datastream_user, mizzou_user), which are
held by attribute number.

RE-MEASURE. `text_length` was `length(coalesce(content, text, text_excerpt,
''))`: a column named for `text` that preferred the capture. A generated
column cannot be altered in place, so it is dropped and re-added preferring
`text`. Measured against production before the change, 165,609 rows:

    changed        5,473
    shrink           835   cleaning had removed chrome
    grow           4,638   `text` longer than the capture
    to zero          527   `text` = '' with a capture present; 289 are
                           not_article, 177 paywall -- rows whose body is
                           the wall, not a story
    from zero          0
    cross 400      501 fall below, 77 rise above

`''` counts as a measured zero, not as absent. coalesce() only skips NULL,
so an article whose cleaned body is the empty string reports 0 -- which is
the answer: cleaning ran and left nothing.

COST. ADD COLUMN ... STORED rewrites the table under an exclusive lock:
165,609 rows, ~1.4 GB, once. Every cron is suspended as this is written and
the three live deployments block rather than fail on the lock. The 30-minute
statement timeout covers the rewrite; the session default of two minutes
would not.

The datadesk console maps an unmanaged Django model onto this table and
declares both the column and the generated expression. Its change ships as
a separate PR that must merge AFTER this migration has run, because merging
it is its deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a7"
down_revision = "z6f7a8b9c0d1"
branch_labels = None
depends_on = None

#: The cleaned body first. `raw` is a fallback for rows extracted before the
#: two columns diverged, where the capture is the only body that exists.
NEW_EXPRESSION = "length(coalesce(text, raw, text_excerpt, ''))"
#: What s4t5u6v7w8x9 created, restored verbatim on downgrade.
OLD_EXPRESSION = "length(coalesce(content, text, text_excerpt, ''))"


def _replace_text_length(expression: str) -> None:
    """Drop and re-create the generated column; it cannot be altered."""
    op.execute("DROP INDEX IF EXISTS ix_articles_text_length")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS text_length")
    op.execute(
        "ALTER TABLE articles ADD COLUMN text_length integer "
        f"GENERATED ALWAYS AS ({expression}) STORED"
    )
    op.create_index(
        "ix_articles_text_length",
        "articles",
        [sa.text("text_length DESC")],
    )


def upgrade() -> None:
    op.execute("SET statement_timeout = '30min'")
    op.execute("ALTER TABLE articles RENAME COLUMN content TO raw")
    _replace_text_length(NEW_EXPRESSION)


def downgrade() -> None:
    op.execute("SET statement_timeout = '30min'")
    op.execute("DROP INDEX IF EXISTS ix_articles_text_length")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS text_length")
    op.execute("ALTER TABLE articles RENAME COLUMN raw TO content")
    op.execute(
        "ALTER TABLE articles ADD COLUMN text_length integer "
        f"GENERATED ALWAYS AS ({OLD_EXPRESSION}) STORED"
    )
    op.create_index(
        "ix_articles_text_length",
        "articles",
        [sa.text("text_length DESC")],
    )
