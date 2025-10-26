# Telemetry Store Implementation Summary

**Last Updated:** October 2025  
**Status:** ✅ Fully Migrated to SQLAlchemy

## Overview
- Unified all telemetry writers on the shared `TelemetryStore` introduced in
  `src/telemetry/store.py`.
- **NEW (Oct 2025):** Migrated from raw `sqlite3` to SQLAlchemy for PostgreSQL/Cloud SQL support.
- Refactored content-cleaning, extraction, and byline telemetry modules to
  share schema management, queueing, and connection lifecycle.
- Full support for both SQLite (local development) and PostgreSQL (Cloud SQL production).

## Why we centralized telemetry
1. Reduce duplicated schema ensure logic spread across multiple utilities.
2. Guarantee consistent retry/flush semantics for long-running batch jobs.
3. Make it trivial to add new telemetry producers without reimplementing queue
   and threading infrastructure.

## Architecture snapshot
### Shared store
- `TelemetryStore` exposes queued (async) or immediate (sync) writes with a
  thread-safe queue and per-job schema ensure support.
- **Database Support:**
  - SQLite: `sqlite:///data/mizzou.db` (default for local development)
  - PostgreSQL: `postgresql+psycopg2://user:pass@host/db` (Cloud SQL production)
  - Automatic DDL adaptation for different database dialects
- Individual jobs can point to alternate databases by instantiating 
  `TelemetryStore(database=..., async_writes=...)`.
- Context manager `store.connection()` provides a sqlite3-compatible interface
  that works with both SQLite and PostgreSQL.
- **Backward Compatible:** Existing telemetry code works without modification.

### Current producers
| Module | Purpose | Notes |
| --- | --- | --- |
| `src/utils/comprehensive_telemetry.py` | Article extraction metrics | Uses sync mode for temp files created in tests and batch sims. |
| `src/utils/content_cleaning_telemetry.py` | Content cleaning audit trail | Leans on async queue for background flushing. |
| `src/utils/byline_telemetry.py` | Byline cleaning traces | Gains shared ensure + `flush()` helper for deterministic tests. |

Additional consumers can request the global store with `get_store()` when they
need to share the same database connection pool.

### SQLAlchemy Migration (October 2025)

**Status:** ✅ Complete

All telemetry producers now work seamlessly with both SQLite and PostgreSQL:

- ✅ `src/utils/byline_telemetry.py` - Fully migrated
- ✅ `src/utils/content_cleaning_telemetry.py` - Fully migrated  
- ✅ `src/utils/extraction_telemetry.py` - Fully migrated
- ✅ `src/utils/comprehensive_telemetry.py` - Fully migrated

**Migration Details:** See `docs/TELEMETRY_STORE_SQLALCHEMY_MIGRATION.md`

**Alembic Migrations:** 
- `alembic/versions/a9957c3054a4_add_remaining_telemetry_tables.py`
- Creates all telemetry tables in PostgreSQL/Cloud SQL

**Tests:** 62/65 telemetry tests passing (95%)

### Developer workflow impact

- Local runs now share a single `TelemetryStore` instance per process, so
  repeated scripts reuse background writer threads automatically.
- Short-lived CLI utilities should call `store.flush()` (or `store.shutdown`)
  before exiting to avoid dropping queued inserts.
- The queue worker logs failures with stack traces; developers can set
  `TELEMETRY_DEBUG=1` to raise exceptions immediately when diagnosing issues.
- Temp-database scenarios (tests, demos, notebooks) should continue to opt
  into `async_writes=False` for deterministic reads.

### Adoption checklist for legacy producers

1. Replace bespoke sqlite connection code with `from src.telemetry.store import
   get_store`.
1. Move any `CREATE TABLE IF NOT EXISTS ...` statements into the `ensure=`
   argument passed to the store's `submit` method.
1. Wrap long-running aggregations in `with store.connection()` to benefit from
   shared pragmas (foreign keys, timeouts).
1. Add a targeted integration test that asserts the new module's data lands in
   the expected telemetry table, mirroring the approach in
   `tests/test_telemetry_system.py`.
1. Update documentation or playbooks to point analysts to the centralised
   telemetry database path if it differs from defaults.

### FAQ / known limitations

- **Is sqlite still viable once telemetry volume grows?** Yes, but monitor the
  queue depth. The new store makes it easier to swap the backend for a remote
  database later if needed.
- **Can multiple processes write concurrently?** Yes. Each process owns its
  writer thread; sqlite's journaling handles concurrent writers with short
  lock contention windows. For very high throughput, consider sharding by
  database path.
- **How do we introspect queue health?** The store exposes a standard library
  `queue.Queue`; enable debug logging (`logging.getLogger('src.telemetry').setLevel`)
  to track enqueue/dequeue events.
- **What about migrations?** DDL caching prevents redundant executions. When
  schemas evolve, add new DDL statements to the `ensure=` list and bump tests
  to exercise them.

## Migration playbook for new telemetry producers

1. **Pick a store:**

  ```python
  from src.telemetry.store import TelemetryStore, get_store

  store = TelemetryStore(database="sqlite:///data/custom.db")  # or get_store()
  ```

1. **Ensure schema inside a write job** (no more ad-hoc `CREATE TABLE` calls):

  ```python
  DDL = """CREATE TABLE IF NOT EXISTS foo (...)"""

  def writer(conn):
    conn.execute("INSERT INTO foo (...) VALUES (...)")

  store.submit(writer, ensure=[DDL])
  ```

1. **Run read queries through `store.connection()`** so tests and production use
   identical connection options:

  ```python
  with store.connection() as conn:
    rows = conn.execute("SELECT * FROM foo").fetchall()
  ```

1. **Integrate flushing in tests or short-lived scripts**:

  ```python
  store.flush()  # waits for queued jobs when async_writes=True
  ```

## Operational notes

- Async mode is still the default; modules that create temporary databases (for
  example the comprehensive telemetry tests) pass `async_writes=False` so that
  inserts are visible immediately.
- The store caches executed DDL statements and only replays them when unseen,
  avoiding redundant migrations on every write.
- Shutdown hooks are registered automatically when the store owns the writer
  thread; call `store.shutdown(wait=True)` for deterministic termination in
  bespoke runners.

## Testing & validation

- `pytest tests/test_telemetry_system.py` now covers end-to-end workflows across
  the refactored producers and asserts database state using column names.
- Additional smoke coverage comes from existing byline/content cleaning tests,
  which continue to pass without modification after swapping in the store.

## Rollout checklist (complete)

- [x] Add shared store module with queue, schema ensure cache, and connection
      helpers.
- [x] Refactor content cleaning telemetry to use the store.
- [x] Refactor comprehensive extraction telemetry to use the store.
- [x] Refactor byline telemetry writer to use the store and expose `flush()`.
- [x] Update telemetry system tests and register the `integration` pytest mark.

## Next steps

- Build lightweight admin reporting utilities that reuse `TelemetryStore` for
  analytical queries (publisher scorecards, HTTP error dashboards).
- Evaluate Prometheus export or SQLite-to-Parquet ETL once the shared store has
  bedded in for a few release cycles.

## Historical context

The previous iteration of this document focused exclusively on the standalone
byline telemetry implementation. That material is archived in Git history for
reference; the new shared store consolidates those capabilities alongside the
rest of our telemetry pipeline.
