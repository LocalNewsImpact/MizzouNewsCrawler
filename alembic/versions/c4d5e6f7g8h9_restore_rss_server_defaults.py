"""Restore server defaults for typed RSS / discovery state columns.

Revision ID: c4d5e6f7g8h9
Revises: c3d4e5f6a7b8
Create Date: 2025-11-09

Purpose:
  The earlier migration (b7c8d9e0f1a2) added typed columns to `sources` with
  temporary server defaults, then dropped those defaults post-backfill. Several
  integration tests perform raw INSERT statements into `sources` without
  specifying these NOT NULL columns; without server defaults this causes
  `NOT NULL` violations. This migration reinstates permanent server defaults
  to ensure minimal INSERTs remain valid and portability across SQLite and
  PostgreSQL is preserved.

Columns affected:
  - rss_consecutive_failures INTEGER NOT NULL DEFAULT 0
  - rss_transient_failures JSON/JSONB NOT NULL DEFAULT []
  - no_effective_methods_consecutive INTEGER NOT NULL DEFAULT 0

Downgrade removes these server defaults (retaining NOT NULL constraints).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision = "c4d5e6f7g8h9"
down_revision = "c3d4e5f6a7b8"  # merge revision unifying RSS + content type heads
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # rss_consecutive_failures
    op.alter_column(
        "sources",
        "rss_consecutive_failures",
        existing_type=sa.Integer(),
        server_default="0",
    )

    # rss_transient_failures
    if dialect == "postgresql":
        # Use jsonb literal for PostgreSQL
        op.alter_column(
            "sources",
            "rss_transient_failures",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
        )
    else:
        op.alter_column(
            "sources",
            "rss_transient_failures",
            existing_type=sa.JSON(),
            server_default="[]",
        )

    # no_effective_methods_consecutive
    op.alter_column(
        "sources",
        "no_effective_methods_consecutive",
        existing_type=sa.Integer(),
        server_default="0",
    )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.alter_column(
        "sources",
        "rss_consecutive_failures",
        existing_type=sa.Integer(),
        server_default=None,
    )

    if dialect == "postgresql":
        op.alter_column(
            "sources",
            "rss_transient_failures",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            server_default=None,
        )
    else:
        op.alter_column(
            "sources",
            "rss_transient_failures",
            existing_type=sa.JSON(),
            server_default=None,
        )

    op.alter_column(
        "sources",
        "no_effective_methods_consecutive",
        existing_type=sa.Integer(),
        server_default=None,
    )
