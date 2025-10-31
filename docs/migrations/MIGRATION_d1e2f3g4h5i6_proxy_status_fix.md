# Migration d1e2f3g4h5i6: Fix proxy_status Column Type

## Overview

**Migration ID**: `d1e2f3g4h5i6_fix_proxy_status_column_type`  
**Date**: 2025-10-31  
**Severity**: CRITICAL  
**Issue**: #123 - Telemetry PostgreSQL schema missing → SQLite fallback → data loss

## Problem Statement

The `extraction_telemetry_v2.proxy_status` column was incorrectly created as `Integer` in migration `c22022d6d3ec`, while the ORM model `ExtractionTelemetryV2` expects it to be `String`. This schema mismatch caused:

1. **PostgreSQL insertion failures** when code tried to insert string values like `'success'`, `'failed'`, `'bypassed'`
2. **SQLite fallback** when PostgreSQL operations failed
3. **Potential data loss** as telemetry data was written to SQLite instead of the production PostgreSQL database

## Root Cause

Migration `c22022d6d3ec_add_proxy_and_alternative_columns_to_` created the column as:
```python
sa.Column('proxy_status', sa.Integer(), nullable=True)
```

But the ORM model defined it as:
```python
proxy_status = Column(String, nullable=True)  # Line 143 in telemetry_orm.py
```

And application code inserted string values:
```python
telemetry.proxy_status = "success"  # or "failed", "bypassed", "disabled"
```

## Solution

This migration changes the `proxy_status` column type from `Integer` to `String` (VARCHAR in PostgreSQL, compatible type in SQLite).

### PostgreSQL
```sql
ALTER TABLE extraction_telemetry_v2 
ALTER COLUMN proxy_status TYPE VARCHAR 
USING proxy_status::VARCHAR
```

### SQLite
Uses batch mode with ALTER COLUMN (SQLite is flexible with types, but we update for consistency).

## Impact

### Before Migration
- ❌ PostgreSQL: INSERT statements with string `proxy_status` values fail
- ❌ System falls back to SQLite
- ❌ Production telemetry data written to wrong database
- ❌ Data loss risk

### After Migration
- ✅ PostgreSQL: Accepts string `proxy_status` values correctly
- ✅ No SQLite fallback
- ✅ Telemetry data written to correct production database
- ✅ No data loss

## Valid proxy_status Values

After this migration, the following string values are accepted:
- `"success"` - Proxy request succeeded
- `"failed"` - Proxy request failed
- `"bypassed"` - Proxy was bypassed
- `"disabled"` - Proxy was disabled
- `NULL` - Proxy not used

## Testing

### Automated Tests
1. **ORM Tests**: `tests/models/test_extraction_telemetry_proxy_status.py`
   - Tests all valid string values
   - Tests NULL values
   - Tests bulk inserts
   - Validates column type in schema

2. **Migration Tests**: `tests/alembic/test_proxy_status_migration.py`
   - Tests migration creates correct column type
   - Tests raw SQL inserts work
   - Tests migration documentation

### Manual Verification
Run the verification script:
```bash
python /tmp/test_telemetry_proxy_status.py
```

Expected output:
```
SUCCESS! All tests passed. ✓
proxy_status column correctly accepts string values.
```

## Deployment Instructions

### Development/Staging

```bash
# 1. Backup database (recommended)
pg_dump -h localhost -U postgres -d mizzou_crawler > backup_before_proxy_fix.sql

# 2. Run migration
alembic upgrade head

# 3. Verify migration applied
alembic current

# Expected output includes: d1e2f3g4h5i6
```

### Production

Follow the standard migration runbook at `docs/MIGRATION_RUNBOOK.md`:

1. **Use GitHub Actions workflow** (recommended)
   - Go to Actions → "Database Migrations"
   - Select production environment
   - Approve manual gate
   - Monitor logs

2. **Manual execution** (if needed)
   ```bash
   # Use the migrator Docker image
   kubectl apply -f k8s/jobs/run-alembic-migrations.yaml
   kubectl logs -l job-name=run-alembic-migrations -f
   ```

## Rollback Plan

### If Issues Occur

```bash
# Downgrade to previous migration
alembic downgrade -1
```

**Warning**: The downgrade will attempt to convert the column back to Integer. This will **fail** if there are string values in the column (which is expected after running application code). In that case:

1. **Do NOT downgrade** - the string values are correct
2. Keep the migration applied
3. Investigate why PostgreSQL is not being used
4. Check database connection configuration

## Verification

After deployment, verify the fix is working:

### 1. Check Column Type
```sql
-- PostgreSQL
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'extraction_telemetry_v2' 
  AND column_name = 'proxy_status';

-- Expected: data_type = 'character varying' or 'varchar'
```

### 2. Test Insert
```sql
-- Insert test record
INSERT INTO extraction_telemetry_v2 (
    operation_id, article_id, url, host,
    start_time, end_time, proxy_status, is_success, created_at
) VALUES (
    'verify-fix', 'test-article', 'https://example.com/test', 'example.com',
    NOW(), NOW(), 'success', true, NOW()
);

-- Verify
SELECT proxy_status FROM extraction_telemetry_v2 WHERE operation_id = 'verify-fix';
-- Expected: 'success'

-- Cleanup
DELETE FROM extraction_telemetry_v2 WHERE operation_id = 'verify-fix';
```

### 3. Check Application Logs
After deployment, monitor application logs for:
- ✅ No SQLite fallback warnings
- ✅ Successful telemetry inserts to PostgreSQL
- ✅ No `proxy_status` type errors

## Related Issues

- **Issue #123**: Telemetry PostgreSQL schema missing → SQLite fallback → data loss
- **Migration c22022d6d3ec**: Original migration that created incorrect column type

## Files Changed

- `alembic/versions/d1e2f3g4h5i6_fix_proxy_status_column_type.py` - Migration file
- `tests/models/test_extraction_telemetry_proxy_status.py` - ORM tests
- `tests/alembic/test_proxy_status_migration.py` - Migration tests
- `docs/migrations/MIGRATION_d1e2f3g4h5i6_proxy_status_fix.md` - This document

## Contact

For questions or issues with this migration:
- Open an issue on GitHub
- Check Slack #infrastructure channel
- Review telemetry documentation in `docs/telemetry/`
