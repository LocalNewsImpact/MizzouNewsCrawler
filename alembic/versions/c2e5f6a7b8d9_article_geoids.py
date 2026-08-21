"""article_geoids: the story-to-FIPS relation, one row per distinct GEOID.

News geography is one-to-many: a regional story belongs to each community in
it. article_places stays mention-grained (with duplicates); this table is the
deduplicated story-level set BigQuery analysis joins through. is_primary marks
the resolved point where one exists.

Revision ID: c2e5f6a7b8d9
Revises: b1d4e5f6a7c8
Create Date: 2026-08-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2e5f6a7b8d9"
down_revision: Union[str, None] = "b1d4e5f6a7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Flat spreadsheet-friendly copy of the set: a JSON array string, e.g.
    # ["2970000","2907966"]. The join table below is the queryable relation.
    op.add_column("article_enrichment", sa.Column("geoids", sa.Text(), nullable=True))
    op.create_table(
        "article_geoids",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "article_id",
            sa.Text(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("geoid", sa.Text(), nullable=False),
        sa.Column("geoid_level", sa.Text(), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("source", sa.Text(), nullable=False),  # point | mention | scope_state
    )
    op.create_index("ix_article_geoids_article_id", "article_geoids", ["article_id"])
    op.create_index("ix_article_geoids_geoid", "article_geoids", ["geoid"])
    op.create_unique_constraint(
        "uq_article_geoids_article_geoid", "article_geoids", ["article_id", "geoid"]
    )


def downgrade() -> None:
    op.drop_table("article_geoids")
    op.drop_column("article_enrichment", "geoids")
