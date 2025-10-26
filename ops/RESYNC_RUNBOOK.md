Resync migration runbook (production)
=====================================

Goal
----
Safely apply the `zzzz_resync_extraction_telemetry_sequence` Alembic migration in
production to resynchronize the `extraction_telemetry_v2.id` sequence and prevent
duplicate-key (23505) errors from telemetry writers.

Prerequisites
-------------
- Database superuser or a role with permission to ALTER sequences and run
  migrations.
- `alembic` available in the deploy environment and configured to use your
  `DATABASE_URL`.
- `pg_dump` available for backups.
- Maintenance window or acceptance of brief write pauses (recommended).

High-level steps
----------------
1. Backup the database
2. Run migrations in staging (if you have staging)
3. Run the resync migration on production
4. Verify sequence consistency
5. Monitor logs for further 23505 occurrences

Detailed steps
--------------
1) Backup production DB (recommended)

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/prod_db
# Dump schema+data; time-consuming for large DBs — adapt flags for speed
pg_dump --format=custom --file=prod_db_backup.dump "$DATABASE_URL"
```

2) (Optional) Run on staging
- Apply the same migration to staging and verify no side effects.

3) Run the migration

```bash
# Ensure alembic.ini is configured to use $DATABASE_URL
export DATABASE_URL=postgresql://user:pass@host:5432/prod_db
alembic upgrade head
```

Note: The `zzzz_resync_extraction_telemetry_sequence` migration is idempotent and
safe to re-run. It will set the telemetry sequence to max(id) so inserts no
longer conflict.

4) Verify sequence

Connect to your DB and run:

```sql
SELECT pg_get_serial_sequence('extraction_telemetry_v2','id') AS seq_name;
SELECT COALESCE(MAX(id), 0) AS max_id FROM extraction_telemetry_v2;
SELECT last_value, is_called FROM <seq_name>;
-- or test nextval (this consumes a sequence value):
SELECT nextval('<seq_name>');
```

Expect `nextval` to be >= `max_id + 1`.

5) Monitor
- Watch for new IntegrityError 23505 occurrences in your telemetry worker logs.
- If 23505 continues, consider: concurrent manual sequence modifications, delayed inserts from replicas, or other parts of the system inserting explicit ids.

Rollback
--------
- No automatic rollback; the migration is an operational one-time fix. If you need to revert, use DB backups.

Safety notes
------------
- The telemetry system is best-effort. Avoid making application behavior depend on perfect telemetry writes.
- Keep the runtime retry/resync guard in telemetry writer code while applying the migration.

Contacts
--------
- On-call DB admin: db-admin@example.com
- Telemetry owner: telemetry@example.com
