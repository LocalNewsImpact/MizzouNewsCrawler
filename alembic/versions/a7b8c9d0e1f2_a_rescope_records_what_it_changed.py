"""A rescope records what it changed.

`enrich rescope` answers one question again -- the story's scope -- under a
newer prompt, and re-places the story only where the new answer requires
it. Each article it reads gets one row here: the scope before and after,
the model's reason, and the point and place set before and after. The
`change` column says which of those moved, so "which records changed, how
and why" is a query rather than a reconstruction.

Rows are never updated. A second rescope of the same article under a later
prompt is a second row.

Revision ID: a7b8c9d0e1f2
Revises: 687d44c97977
Create Date: 2026-11-17 14:30:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "687d44c97977"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enrichment_rescope_log",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column(
            "article_id",
            sa.Text(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_slug", sa.Text(), nullable=False),
        sa.Column(
            "rescoped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        # unchanged | scope_only | point_added | point_removed | point_moved
        # | place_set_changed | error
        sa.Column("change", sa.Text(), nullable=False),
        sa.Column("old_scope", sa.Text(), nullable=True),
        sa.Column("new_scope", sa.Text(), nullable=True),
        sa.Column("old_confidence", sa.Float(), nullable=True),
        sa.Column("new_confidence", sa.Float(), nullable=True),
        sa.Column("old_rationale", sa.Text(), nullable=True),
        sa.Column("new_rationale", sa.Text(), nullable=True),
        sa.Column("old_point_place", sa.Text(), nullable=True),
        sa.Column("new_point_place", sa.Text(), nullable=True),
        sa.Column("old_point_method", sa.Text(), nullable=True),
        sa.Column("new_point_method", sa.Text(), nullable=True),
        sa.Column("old_point_geoid", sa.Text(), nullable=True),
        sa.Column("new_point_geoid", sa.Text(), nullable=True),
        sa.Column("old_geoids", sa.JSON(), nullable=True),
        sa.Column("new_geoids", sa.JSON(), nullable=True),
        sa.Column("old_geo_skip_reason", sa.Text(), nullable=True),
        sa.Column("new_geo_skip_reason", sa.Text(), nullable=True),
        sa.Column("focus_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_enrichment_rescope_log_article_id",
        "enrichment_rescope_log",
        ["article_id"],
    )
    op.create_index(
        "ix_enrichment_rescope_log_run_change",
        "enrichment_rescope_log",
        ["run_id", "change"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_enrichment_rescope_log_run_change", table_name="enrichment_rescope_log"
    )
    op.drop_index(
        "ix_enrichment_rescope_log_article_id", table_name="enrichment_rescope_log"
    )
    op.drop_table("enrichment_rescope_log")
