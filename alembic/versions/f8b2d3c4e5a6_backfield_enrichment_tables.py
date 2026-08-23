"""Backfield enrichment: two articles columns and four result tables.

Phase 1 of docs/BACKFIELD_IMPLEMENTATION.md. Tables hold the output of the
enrichment stage (docs/BACKFIELD_ENRICHMENT.md §9); each is synced to BigQuery
by its own scheduled query, created in Phase 2. No writer exists until Phase 5,
so after this migration the tables are empty in production.

steps_applied is text[] with a GIN index on PostgreSQL, per the spec — it is the
key reprocessing queries filter on. SQLite (used by the migration test harness)
gets a JSON column; the production shape is the PostgreSQL one.

Revision ID: f8b2d3c4e5a6
Revises: e7a1c2b3d4f5
Create Date: 2026-08-21

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f8b2d3c4e5a6"
down_revision: Union[str, None] = "e7a1c2b3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    steps_type = postgresql.ARRAY(sa.Text()) if _is_postgres() else sa.JSON()

    op.add_column("articles", sa.Column("enriched_at", sa.DateTime(), nullable=True))
    op.add_column(
        "articles",
        sa.Column(
            "enrichment_attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_table(
        "article_enrichment",
        sa.Column(
            "article_id",
            sa.Text(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # provenance and reprocessing control
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("steps_applied", steps_type, nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("backfield_commit", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_versions", sa.JSON(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "enriched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # content gate
        sa.Column("is_news_content", sa.Boolean(), nullable=True),
        sa.Column("content_gate_reason", sa.Text(), nullable=True),
        # one column per metadata preset, each with its confidence
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("scope_confidence", sa.Float(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("subject_confidence", sa.Float(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("topic_confidence", sa.Float(), nullable=True),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("format_confidence", sa.Float(), nullable=True),
        sa.Column("timeframe", sa.Text(), nullable=True),
        sa.Column("timeframe_confidence", sa.Float(), nullable=True),
        sa.Column("user_need", sa.Text(), nullable=True),
        sa.Column("user_need_confidence", sa.Float(), nullable=True),
        sa.Column("rationales", sa.JSON(), nullable=True),
        # resolved location, when scope is point-level
        sa.Column("point_place", sa.Text(), nullable=True),
        sa.Column("point_method", sa.Text(), nullable=True),
        sa.Column("point_lat", sa.Float(precision=53), nullable=True),
        sa.Column("point_lon", sa.Float(precision=53), nullable=True),
        sa.Column("point_gnis", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_article_enrichment_profile_version",
        "article_enrichment",
        ["profile_version"],
    )
    if _is_postgres():
        op.create_index(
            "ix_article_enrichment_steps_applied",
            "article_enrichment",
            ["steps_applied"],
            postgresql_using="gin",
        )

    op.create_table(
        "article_places",
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
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("place_type", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("county", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mention_text", sa.Text(), nullable=True),
        sa.Column("is_point", sa.Boolean(), nullable=True),
        sa.Column("lat", sa.Float(precision=53), nullable=True),
        sa.Column("lon", sa.Float(precision=53), nullable=True),
        sa.Column("geocoder", sa.Text(), nullable=True),
    )
    op.create_index("ix_article_places_article_id", "article_places", ["article_id"])
    op.create_index("ix_article_places_city_state", "article_places", ["city", "state"])

    op.create_table(
        "article_people",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_key", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("affiliation", sa.Text(), nullable=True),
        sa.Column("person_type", sa.Text(), nullable=True),
        sa.Column("role_in_story", sa.Text(), nullable=True),
        sa.Column("nature", sa.Text(), nullable=True),
        sa.Column("public_figure", sa.Boolean(), nullable=True),
        sa.Column("mention_count", sa.Integer(), nullable=True),
        sa.Column("quotes", sa.JSON(), nullable=True),
    )
    op.create_index("ix_article_people_article_id", "article_people", ["article_id"])
    op.create_index("ix_article_people_sort_key", "article_people", ["sort_key"])

    op.create_table(
        "article_organizations",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("org_type", sa.Text(), nullable=True),
        sa.Column("boundary", sa.Text(), nullable=True),
        sa.Column("role_in_story", sa.Text(), nullable=True),
        sa.Column("nature", sa.Text(), nullable=True),
        sa.Column("mention_count", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_article_organizations_article_id", "article_organizations", ["article_id"]
    )


def downgrade() -> None:
    op.drop_table("article_organizations")
    op.drop_table("article_people")
    op.drop_table("article_places")
    op.drop_table("article_enrichment")
    op.drop_column("articles", "enrichment_attempts")
    op.drop_column("articles", "enriched_at")
