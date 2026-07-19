"""Add unique constraint on articles.url

Production had NO uniqueness on articles.url — a 2025-11-20 commit claimed to
add it but never reached prod (schema drift). Real duplicate extractions
accumulated (377 URL groups, 380 excess rows) until the smoke test's first
actual run caught it on 2026-07-18. Production was deduped and the constraint
created there manually on 2026-07-19 (CREATE UNIQUE INDEX CONCURRENTLY, then
ALTER TABLE ... ADD CONSTRAINT ... USING INDEX so it registers in
information_schema.table_constraints). This migration codifies it for
dev/test databases.

The extraction insert path already uses ON CONFLICT DO NOTHING, written in
anticipation of exactly this constraint.

Revision ID: c4e8a1f52b7d
Revises: b2d9f4c7e1a3
Create Date: 2026-07-19
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c4e8a1f52b7d"
down_revision = "b2d9f4c7e1a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Idempotent: production already carries the constraint (created
        # out-of-band via CONCURRENTLY + USING INDEX to avoid table locks).
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_articles_url'
                ) THEN
                    ALTER TABLE articles
                        ADD CONSTRAINT uq_articles_url UNIQUE (url);
                END IF;
            END $$;
            """
        )
    else:
        # SQLite (unit-test databases): a unique index is the equivalent.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_url ON articles (url)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE articles DROP CONSTRAINT IF EXISTS uq_articles_url")
    else:
        op.execute("DROP INDEX IF EXISTS uq_articles_url")
