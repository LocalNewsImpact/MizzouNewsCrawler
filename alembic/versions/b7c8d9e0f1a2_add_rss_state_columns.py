"""Add typed RSS state columns to sources and backfill from JSON metadata.

Revision ID: b7c8d9e0f1a2
Revises: (previous head)
Create Date: 2025-11-08

This migration replaces reliance on JSON metadata keys for RSS and
"no effective methods" tracking by adding first-class typed columns.

Columns added:
  - rss_consecutive_failures INTEGER NOT NULL DEFAULT 0
  - rss_transient_failures JSON/JSONB NOT NULL DEFAULT []
  - rss_missing_at TIMESTAMP NULL
  - rss_last_failed_at TIMESTAMP NULL
  - last_successful_method VARCHAR(32)
  - no_effective_methods_consecutive INTEGER NOT NULL DEFAULT 0
  - no_effective_methods_last_seen TIMESTAMP NULL

Backfill strategy:
  * For PostgreSQL: single bulk UPDATE using JSON operators/casts.
  * For other dialects (e.g. SQLite dev): row-by-row Python extraction.

Legacy metadata keys are left in place (non-destructive) to allow
rolling refactor; application code will switch to columns.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import json

# Revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "d3e3764ec645"  # merge head prior to adding typed RSS state columns
branch_labels = None
depends_on = None


def _json_value(meta, key):  # defensive helper for non-Postgres backfill
    if not isinstance(meta, (dict, list)):
        return None
    if isinstance(meta, dict):
        return meta.get(key)
    return None


def upgrade():  # noqa: C901 - complexity acceptable for migration
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Choose JSON column type based on dialect for portability
    if dialect == "postgresql":
        json_type = postgresql.JSONB(astext_type=sa.Text())
    else:
        json_type = sa.JSON()

    # Add columns with server defaults to populate existing rows
    op.add_column(
        "sources",
        sa.Column(
            "rss_consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "rss_transient_failures", json_type, nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "sources",
        sa.Column("rss_missing_at", sa.TIMESTAMP(timezone=False), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("rss_last_failed_at", sa.TIMESTAMP(timezone=False), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("last_successful_method", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column(
            "no_effective_methods_consecutive",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "no_effective_methods_last_seen",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
        ),
    )

    # Backfill from legacy JSON metadata if available
    if dialect == "postgresql":
        # Bulk update leveraging JSONB operators; tolerate missing / malformed
        # values. Simpler approach: attempt cast; if invalid it becomes NULL.
        backfill_sql = sa.text(
            """
            UPDATE sources
            SET
                            rss_consecutive_failures = COALESCE(
                                (metadata->>'rss_consecutive_failures')::int, 0
                            ),
                            rss_transient_failures = COALESCE(
                                (metadata->'rss_transient_failures')::jsonb, '[]'::jsonb
                            ),
                            rss_missing_at = (
                CASE
                    WHEN ((metadata::jsonb) ? 'rss_missing') THEN
                        NULLIF(metadata->>'rss_missing','')::timestamp
                    ELSE NULL
                END
              ),
              rss_last_failed_at = (
                CASE
                    WHEN ((metadata::jsonb) ? 'rss_last_failed') THEN
                        NULLIF(metadata->>'rss_last_failed','')::timestamp
                  ELSE NULL
                END
              ),
                                            last_successful_method = NULLIF(
                                                metadata->>'last_successful_method',''
                                            ),
                            no_effective_methods_consecutive = COALESCE(
                                (metadata->>'no_effective_methods_consecutive')::int, 0
                            ),
                            no_effective_methods_last_seen = (
                                CASE
                                    WHEN (
                                        (metadata::jsonb) ?
                                        'no_effective_methods_last_seen'
                                    ) THEN
                                        NULLIF(
                                            metadata->>'no_effective_methods_last_seen',''
                                        )::timestamp
                                    ELSE NULL
                                END
                            )
            WHERE metadata IS NOT NULL;
            """
        )
        bind.execute(backfill_sql)
    else:
        # Fallback row-wise Python migration for SQLite or other dialects
        sources_table = sa.table(
            "sources",
            sa.column("id"),
            sa.column("metadata"),
        )
        result = bind.execute(sa.select(sources_table.c.id, sources_table.c.metadata))
        update_stmt = sa.text(
            """
            UPDATE sources SET
              rss_consecutive_failures = :rcf,
              rss_transient_failures = :rtf,
              rss_missing_at = :rma,
              rss_last_failed_at = :rlf,
              last_successful_method = :lsm,
              no_effective_methods_consecutive = :nemc,
              no_effective_methods_last_seen = :nemls
            WHERE id = :id
            """
        )
        for row in result.fetchall():  # type: ignore
            meta_raw = row.metadata
            try:
                if isinstance(meta_raw, str):
                    meta = json.loads(meta_raw)
                else:
                    meta = meta_raw or {}
            except Exception:
                meta = {}
            rcf = _json_value(meta, "rss_consecutive_failures") or 0
            transient = _json_value(meta, "rss_transient_failures") or []
            rma = _json_value(meta, "rss_missing") or None
            rlf = _json_value(meta, "rss_last_failed") or None
            lsm = _json_value(meta, "last_successful_method") or None
            nemc = _json_value(meta, "no_effective_methods_consecutive") or 0
            nemls = _json_value(meta, "no_effective_methods_last_seen") or None
            bind.execute(
                update_stmt,
                {
                    "rcf": (
                        int(rcf)
                        if isinstance(rcf, (int, str)) and str(rcf).isdigit()
                        else 0
                    ),
                    "rtf": json.dumps(transient if isinstance(transient, list) else []),
                    "rma": rma,
                    "rlf": rlf,
                    "lsm": lsm,
                    "nemc": (
                        int(nemc)
                        if isinstance(nemc, (int, str)) and str(nemc).isdigit()
                        else 0
                    ),
                    "nemls": nemls,
                    "id": row.id,
                },
            )

    # Drop server defaults (keep NULL constraints) for cleaner future inserts
    op.alter_column("sources", "rss_consecutive_failures", server_default=None)
    op.alter_column("sources", "rss_transient_failures", server_default=None)
    op.alter_column("sources", "no_effective_methods_consecutive", server_default=None)


def downgrade():
    # Remove columns (data loss for new columns). Metadata keys remain untouched.
    op.drop_column("sources", "no_effective_methods_last_seen")
    op.drop_column("sources", "no_effective_methods_consecutive")
    op.drop_column("sources", "last_successful_method")
    op.drop_column("sources", "rss_last_failed_at")
    op.drop_column("sources", "rss_missing_at")
    op.drop_column("sources", "rss_transient_failures")
    op.drop_column("sources", "rss_consecutive_failures")
