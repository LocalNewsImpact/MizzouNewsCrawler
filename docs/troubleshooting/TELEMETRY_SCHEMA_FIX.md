# Telemetry Schema Fix: ON CONFLICT Bug Resolution

## Issue Summary

**Critical Production Bug Discovered During Test Development**

The telemetry system had a schema bug that would cause runtime failures in production PostgreSQL:
- Code uses `ON CONFLICT(host, status_code)` for upsert operations
- Both PostgreSQL and SQLite require a UNIQUE constraint for ON CONFLICT to work
- Original migration `a1b2c3d4e5f6` created `http_error_summary` table WITHOUT the UNIQUE constraint
- This would cause `OperationalError` when trying to insert duplicate (host, status_code) pairs

## Root Cause Analysis

### The Code (src/utils/comprehensive_telemetry.py)

```python
conn.execute(
    """
    INSERT INTO http_error_summary
    (host, status_code, error_type, count, last_seen)
    VALUES (?, ?, ?, 1, ?)
    ON CONFLICT(host, status_code) DO UPDATE SET
        count = count + 1,
        last_seen = ?
    """,
    (metrics.host, metrics.http_status_code, metrics.http_error_type, now, now)
)
```

### The Original Schema (Migration a1b2c3d4e5f6)

```python
op.create_table(
    'http_error_summary',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('host', sa.String(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.Column('error_type', sa.String(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('first_seen', sa.DateTime(), nullable=False),
    sa.Column('last_seen', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    # ❌ MISSING: UNIQUE constraint on (host, status_code)
)
```

### Database Behavior

**PostgreSQL:**
- `ON CONFLICT(column_list)` requires either:
  - A UNIQUE constraint on those columns, OR
  - A UNIQUE index on those columns
- Without constraint: `ERROR: there is no unique or exclusion constraint matching the ON CONFLICT specification`

**SQLite:**
- `ON CONFLICT(column_list)` requires:
  - An explicit UNIQUE constraint in the table definition
- Without constraint: `sqlite3.OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint`

## The Solution

### New Migration: 805164cd4665

Created `alembic/versions/805164cd4665_add_unique_constraint_http_error_summary.py`:

```python
def upgrade() -> None:
    """Upgrade schema."""
    # Add UNIQUE constraint on (host, status_code) to support ON CONFLICT
    # This is required for the upsert operation in comprehensive_telemetry.py
    op.create_unique_constraint(
        'uq_http_error_summary_host_status',
        'http_error_summary',
        ['host', 'status_code']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove UNIQUE constraint
    op.drop_constraint(
        'uq_http_error_summary_host_status',
        'http_error_summary',
        type_='unique'
    )
```

### Test Infrastructure

Updated `tests/test_telemetry_system.py` to:
1. Create telemetry tables manually (since tests use temporary databases without Alembic)
2. Include the UNIQUE constraint in the test schema
3. Document that test schema now matches production (after migration 805164cd4665)

```python
def create_telemetry_tables(db_path: str) -> None:
    """Create telemetry tables manually for testing (without Alembic).
    
    This replicates the schema from Alembic migrations.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Create http_error_summary table
    # NOTE: UNIQUE(host, status_code) is required for ON CONFLICT to work.
    # This matches the production schema after migration 805164cd4665.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS http_error_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            error_type TEXT NOT NULL,
            count INTEGER NOT NULL,
            first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP NOT NULL,
            UNIQUE(host, status_code)  -- ✅ Added
        )
    """)
    # ... rest of schema ...
```

## Test Results

### Before Fix
- **Telemetry Tests**: 0/14 passing (tables missing)
- **After Manual Table Creation**: 11/14 passing (ON CONFLICT errors)
- **After Schema Fix**: **14/14 passing** ✅

### Test Coverage
All telemetry tests now pass:
1. `test_database_initialization` ✅
2. `test_save_metrics_success` ✅
3. `test_save_metrics_with_http_error` ✅ (was failing)
4. `test_get_field_extraction_stats` ✅
5. `test_get_method_performance_stats` ✅
6. `test_get_publisher_stats` ✅
7. `test_get_top_errors` ✅
8. `test_track_method_attempts` ✅
9. `test_track_http_errors` ✅ (was failing)
10. `test_successful_extraction` ✅
11. `test_failed_extraction_with_retry` ✅
12. `test_partial_extraction` ✅
13. `test_telemetry_database_integration` ✅ (was failing)
14. `test_complete_workflow_simulation` ✅ (was failing)

## Impact Assessment

### Production Risk (Before Fix)
- **Severity**: HIGH
- **Likelihood**: 100% (would fail on first duplicate error)
- **Impact**: Telemetry system would crash on any repeated HTTP error from same host
- **Detection**: Only caught during test development (good catch!)

### Deployment Requirements

**For Local Development:**
```bash
source venv/bin/activate
alembic upgrade head
```

**For Cloud SQL Production:**
The migration will be applied automatically during next deployment via:
1. GCP Cloud Build builds processor image
2. Kubernetes deployment runs Alembic migrations
3. Migration 805164cd4665 adds UNIQUE constraint
4. Telemetry system works correctly

**Important:** This is a **non-breaking** migration:
- Adding UNIQUE constraint is safe (no data loss)
- If table already has duplicate (host, status_code) rows, migration will fail
- Current telemetry code hasn't been running in production yet, so no duplicates exist

## Testing Strategy Resolution

### User Question: "How do we test to a Postgres appropriate standard?"

**Answer:** We test with schema parity.

1. **Test Infrastructure**: SQLite with manually created schema
2. **Schema Source of Truth**: Alembic migrations (PostgreSQL-focused)
3. **Test Schema Maintenance**: `create_telemetry_tables()` replicates migration schema
4. **Validation**: Tests verify behavior that works identically in SQLite and PostgreSQL

### Why This Works

**SQLite vs PostgreSQL for Telemetry:**
- Standard SQL operations (INSERT, SELECT, UPDATE)
- ON CONFLICT behavior identical when UNIQUE constraint exists
- TIMESTAMP types work similarly for our use case
- No advanced PostgreSQL features needed (JSONB, arrays, etc.)

**When to Use PostgreSQL Tests:**
- Advanced PostgreSQL features (JSONB operators, full-text search, etc.)
- Connection pooling and concurrency
- Performance testing at scale
- Replication and failover

**For This Case:**
- ✅ SQLite tests are sufficient (standard SQL, schema parity maintained)
- ✅ Production bug was caught by proper schema alignment
- ✅ No PostgreSQL-specific features in telemetry code

## Lessons Learned

1. **ON CONFLICT requires constraints**: Always verify constraint exists before using ON CONFLICT
2. **Test schema must match production**: Manual table creation must replicate migrations exactly
3. **Cross-database testing catches schema bugs**: SQLite tests revealed PostgreSQL schema issue
4. **Schema documentation is critical**: Comments in tests explain alignment with production

## Next Steps

1. ✅ **Migration created**: 805164cd4665_add_unique_constraint_http_error_summary.py
2. ✅ **Tests updated**: All 14 telemetry tests passing
3. ✅ **Documentation**: This file explains the fix
4. ⏳ **Deploy to production**: Run `alembic upgrade head` (will happen automatically in GCP)
5. ⏳ **Monitor**: Verify telemetry data is being collected correctly

## References

- **PostgreSQL ON CONFLICT**: https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT
- **SQLite ON CONFLICT**: https://www.sqlite.org/lang_conflict.html
- **Alembic Migrations**: https://alembic.sqlalchemy.org/en/latest/
- **Migration File**: `alembic/versions/805164cd4665_add_unique_constraint_http_error_summary.py`
- **Test File**: `tests/test_telemetry_system.py`
- **Production Code**: `src/utils/comprehensive_telemetry.py` (lines 367-382)
