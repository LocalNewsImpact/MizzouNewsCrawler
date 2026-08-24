"""Keep the content gate's verdict, not only its prose.

The gate answers with a verdict from a fixed set -- news, paywall, not_news
-- and a sentence explaining it. `run_content_gate` validates the verdict
against that set and then only the sentence is stored, alongside a boolean
derived from whether enrichment finished.

So the one field that could be counted was discarded and the one that
survived cannot be: 15,747 rows carry 6,280 distinct reasons, because a
model wrote each one. "Story content present in both samples", the same
with a full stop, "Full story content present", and six thousand more.

Nothing downstream can ask how many articles a publisher lost to a
paywall, which is a question the enrichment already answered every time.

Revision ID: c3d4e5f6a7b8
Revises: 9e4c7a1b2d8f
"""

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "9e4c7a1b2d8f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "article_enrichment",
        sa.Column("content_gate_verdict", sa.Text(), nullable=True),
    )
    # Rows already enriched keep a null: the verdict was never recorded and
    # inferring it from the prose would be guessing at what a model meant.
    # A backfill is a re-run, not a migration.
    op.create_index(
        "ix_article_enrichment_gate_verdict",
        "article_enrichment",
        ["content_gate_verdict"],
    )


def downgrade() -> None:
    op.drop_index("ix_article_enrichment_gate_verdict", "article_enrichment")
    op.drop_column("article_enrichment", "content_gate_verdict")
