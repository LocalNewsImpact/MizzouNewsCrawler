Resync extraction_telemetry_v2 sequence
=====================================

Purpose
-------
Out-of-sync Postgres sequences for telemetry tables (e.g., `extraction_telemetry_v2.id`) can
cause duplicate-key errors (23505) in background telemetry writers. This document explains how
to run the one-time Alembic resync migration and how to verify sequence consistency.

Alembic migration
-----------------
A migration already exists in `alembic/versions/zzzz_resync_extraction_telemetry_sequence.py`.
To apply it to your production database:

1. Ensure you have a safe maintenance window (optional but recommended).

1. Run the Alembic upgrade to head against your production DB:

```bash
# Example: set DATABASE_URL for production
export DATABASE_URL=postgresql://<user>:<pass>@<host>:<port>/<db>
alembic upgrade head
```

1. The migration will set the telemetry sequence to the current max(id).

Verification
------------
After running the migration, verify that the sequence for `extraction_telemetry_v2.id` is set
so that the next `nextval()` call will be > max(id):

```sql
-- Connect to your DB and run:
SELECT pg_get_serial_sequence('extraction_telemetry_v2','id') as seq_name;
-- Example output: extraction_telemetry_v2_id_seq

-- Check the current max(id)
SELECT COALESCE(MAX(id), 0) AS max_id FROM extraction_telemetry_v2;

-- Check the sequence's last_value / nextval
SELECT last_value, is_called FROM extraction_telemetry_v2_id_seq;
-- Or ask for the next value (consumes sequence value):
SELECT nextval('extraction_telemetry_v2_id_seq');

-- The nextval should be >= max_id + 1
```

Notes and recommendations
-------------------------
- This migration is safe and idempotent; it only sets the sequence value.
- If you have multiple telemetry tables or other sequences, create similar migrations for them.
- Keep the runtime retry/resync guard in telemetry writer code (it reduces disruption while
  the migration is run and protects from transient races).
- Monitor logs for continued IntegrityError occurrences (23505). If they persist, investigate
  concurrent insertion paths and sequence usage.

Rollback
--------
There is no meaningful downgrade for this operational migration (it is a no-op on downgrade).
If you need to revert sequence changes, consult your DB backups and avoid manual sequence
manipulation unless necessary.
