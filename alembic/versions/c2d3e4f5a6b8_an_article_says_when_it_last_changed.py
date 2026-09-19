"""An article says when it last changed.

Revision ID: c2d3e4f5a6b8
Revises: b1c2d3e4f5a7
Create Date: 2026-09-19

`articles` had no answer to "what changed recently". Six timestamps each
covered ONE stage -- `extracted_at` the body, `labels_updated_at` the CIN
label, `entities_extracted_at`, `enriched_at`, `wire_check_attempted_at`,
`created_at` the insert -- and a status change, a headline repair, a metadata
write or a deliberate retraction moved none of them. The 12 headline repairs
and the 226-row shared-body retraction of 2026-09-19 left no trace any
time-ordered query could find.

WHY A TRIGGER AND NOT A GENERATED COLUMN
----------------------------------------
A generated `GREATEST(...)` of the six would be cheaper and is blind to
exactly the writes that matter: status-only and metadata-only updates, which
is most of what a curation pass does. It would also be blind to every writer
outside this repository -- the datadesk console updates `author`, `title`,
`raw`, `text`, `status`, `metadata` and `enrichment_attempts` as
`datadesk_rw`, through its own Django models, and nothing here can make it
remember to set a column.

A `BEFORE INSERT OR UPDATE` trigger is the only form that catches all of them,
it lives with the table rather than with any caller.

ORDER MATTERS IN THIS MIGRATION
-------------------------------
The column is added NULLable, backfilled, and only then given its default and
NOT NULL -- an `ADD COLUMN ... DEFAULT now()` is a volatile default and
rewrites all 165,649 rows. The trigger is created LAST, after the backfill,
so the backfill's own UPDATE does not stamp every row with the migration's
clock and destroy the history it is trying to preserve.

The backfill takes the latest stage timestamp a row can show, falling back to
`created_at`. That is not the true last-modified for rows edited before today
-- nothing recorded it -- but it is the best evidence on the row, and it is
monotonic with reality rather than arbitrary.
"""

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b8"
down_revision = "b1c2d3e4f5a7"
branch_labels = None
depends_on = None

TRIGGER_FUNCTION = "articles_stamp_last_modified"
TRIGGER = "trg_articles_last_modified"


def upgrade() -> None:
    op.execute("SET statement_timeout = '30min'")
    op.execute("ALTER TABLE articles ADD COLUMN last_modified timestamp")
    # The best evidence already on the row. `created_at` is the floor: every
    # row has one, and a row never changed is correctly stamped with it.
    op.execute("""
        UPDATE articles SET last_modified = GREATEST(
            created_at,
            coalesce(extracted_at, created_at),
            coalesce(labels_updated_at, created_at),
            coalesce(entities_extracted_at, created_at),
            coalesce(enriched_at, created_at),
            coalesce(wire_check_attempted_at, created_at)
        )
        """)
    op.execute(
        "ALTER TABLE articles ALTER COLUMN last_modified SET DEFAULT now(), "
        "ALTER COLUMN last_modified SET NOT NULL"
    )
    # Descending, because every question asked of this column is "what changed
    # most recently"; the planner reads a btree either way.
    op.create_index(
        "ix_articles_last_modified",
        "articles",
        [sa.text("last_modified DESC")],
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            -- An UPDATE that changes nothing still stamps: the caller asked for
            -- a write, and "somebody touched this row" is the question.
            -- On INSERT an explicit value is kept (a backfill or an import
            -- may carry a real timestamp); NULL is filled. SQLAlchemy sends
            -- an explicit NULL for any column it does not know has a
            -- default, so the column DEFAULT alone does not cover INSERT.
            IF TG_OP = 'INSERT' THEN
                NEW.last_modified := coalesce(NEW.last_modified, now());
            ELSE
                NEW.last_modified := now();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """)
    op.execute(
        f"CREATE TRIGGER {TRIGGER} BEFORE INSERT OR UPDATE ON articles "
        f"FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION}()"
    )
    # The console writes as `datadesk_rw` and the crawler as `mizzou_user`; a
    # trigger runs as the table owner, so neither needs a new grant. The column
    # is granted read so the console can sort on it.
    # Conditional: these roles exist in production and not in a test database,
    # and a migration that only runs where the roles happen to exist is a
    # migration that is never tested.
    op.execute("""
        DO $$
        DECLARE r text;
        BEGIN
            FOREACH r IN ARRAY ARRAY['datadesk_ro', 'datadesk_rw'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format(
                        'GRANT SELECT (last_modified) ON articles TO %I', r
                    );
                END IF;
            END LOOP;
        END $$
        """)


def downgrade() -> None:
    op.execute("SET statement_timeout = '30min'")
    op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON articles")
    op.execute(f"DROP FUNCTION IF EXISTS {TRIGGER_FUNCTION}()")
    op.execute("DROP INDEX IF EXISTS ix_articles_last_modified")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS last_modified")
