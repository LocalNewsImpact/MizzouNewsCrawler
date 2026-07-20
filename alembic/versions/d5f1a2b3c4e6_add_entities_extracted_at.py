"""Record entity-extraction state on articles instead of deriving it.

Finding pending work used to be an anti-join against article_entities, which
cost O(corpus) to locate a handful of rows and grew more expensive as the
pipeline got further ahead — eventually exceeding the 120s statement_timeout on
the mizzou_user role and failing every cycle.

``entities_extracted_at`` plus a partial index over exactly the pending
predicate makes that lookup proportional to work outstanding instead, and the
index shrinks as the queue drains.

Revision ID: d5f1a2b3c4e6
Revises: c4e8a1f52b7d
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5f1a2b3c4e6"
down_revision: str | Sequence[str] | None = "c4e8a1f52b7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "idx_articles_pending_entities"


def upgrade() -> None:
    # The mizzou_user role carries statement_timeout=120s — the ceiling that
    # turned this query's slowness into an outage. The backfill below touches
    # ~122k rows, so lift it for this migration or the fix trips over the same
    # limit it exists to escape.
    op.execute("SET statement_timeout='900s'")

    op.add_column(
        "articles",
        sa.Column("entities_extracted_at", sa.DateTime(), nullable=True),
    )

    # Stamp everything already processed BEFORE the new query goes live, or it
    # would treat 122k finished articles as pending and reprocess the corpus.
    op.execute("""
        UPDATE articles a
        SET entities_extracted_at = COALESCE(src.first_seen, NOW())
        FROM (
            SELECT article_id, MIN(created_at) AS first_seen
            FROM article_entities
            GROUP BY article_id
        ) src
        WHERE a.id = src.article_id
          AND a.entities_extracted_at IS NULL
    """)

    # Mirrors the candidate query's WHERE clause so the planner can use it.
    op.create_index(
        INDEX_NAME,
        "articles",
        ["candidate_link_id"],
        unique=False,
        postgresql_where=sa.text(
            "entities_extracted_at IS NULL "
            "AND content IS NOT NULL "
            "AND text IS NOT NULL "
            "AND status NOT IN ('error', 'paywall', 'wire')"
        ),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="articles")
    op.drop_column("articles", "entities_extracted_at")
