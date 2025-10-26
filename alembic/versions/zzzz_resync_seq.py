"""resync_extraction_telemetry_sequence

Revision ID: zzzz_resync_seq
Revises: a1b2c3d4e5f6
Create Date: 2024-10-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision = 'zzzz_resync_seq'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Check if we're using PostgreSQL
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == 'postgresql'
    
    if not is_postgresql:
        # SQLite doesn't have sequences - skip this migration
        return
    
    # Use SQL to set the telemetry sequence to max(id) on the table
    op.execute(
        """
        DO $$
        DECLARE
            seq_name text;
            max_id bigint;
        BEGIN
            SELECT pg_get_serial_sequence(
                'extraction_telemetry_v2', 'id'
            ) INTO seq_name;
            IF seq_name IS NULL THEN
                RAISE NOTICE 'No serial sequence found for extraction_telemetry_v2.id';
                RETURN;
            END IF;
            EXECUTE format(
                'SELECT COALESCE(MAX(id), 0) FROM extraction_telemetry_v2'
            ) INTO max_id;
            IF max_id IS NULL THEN
                max_id := 0;
            END IF;
            -- Set sequence value to max_id (minimum 1), so nextval will return max_id+1
            -- PostgreSQL sequences must have a value >= 1
            EXECUTE format('SELECT setval(%L, GREATEST(%s, 1))', seq_name, max_id);
            RAISE NOTICE 'Resynced sequence % to %', seq_name, GREATEST(max_id, 1);
        END
        $$;
        """
    )


def downgrade():
    # No-op: sequence resync is a one-time operational fix
    pass
