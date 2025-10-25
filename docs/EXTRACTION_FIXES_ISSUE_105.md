# Extraction Workflow Fixes - Issue #105

## Summary

This document describes the fixes implemented for the extraction workflow failure where extraction ran but articles were not being written to the database for 48+ hours.

## Root Causes

1. **Silent Commit Failures**: Database commits appeared to succeed but data wasn't persisted
2. **Database Connection Issues**: Extractor potentially connecting to different database than expected
3. **Missing Duplicate Prevention**: No UNIQUE constraint on `articles.url` allowed duplicates
4. **Insufficient Debugging**: No way to verify exact SQL queries being executed

## Fixes Implemented

### 1. Post-Commit Verification

**File**: `src/cli/commands/extraction.py`

Added verification query after each article insert to catch silent commit failures:

```python
# After session.commit()
verify_query = text("SELECT id FROM articles WHERE id = :id")
verify_result = session.execute(verify_query, {"id": article_id}).fetchone()

if verify_result is None:
    logger.error(
        "❌ POST-COMMIT VERIFICATION FAILED: Article %s was not found "
        "in database after commit. This indicates a silent commit failure!",
        article_id
    )
```

**Impact**: Immediately detects if an article wasn't actually written to the database, providing clear error messages for debugging.

### 2. SQL Query Debugging

**File**: `src/cli/commands/extraction.py`

Added `EXTRACTION_DUMP_SQL` environment variable to log exact SQL queries:

```bash
# Enable SQL dumping
export EXTRACTION_DUMP_SQL=true

# Run extraction
python -m src.cli.cli_modular extract --limit 20 --batches 1
```

This logs the exact SQL query and parameters before execution, allowing reproduction in `psql` for debugging.

### 3. Enhanced Database Logging

**File**: `src/models/database.py`

Added logging at DatabaseManager initialization to show:
- Database URL being used (with password masked)
- Connection type (SQLite, PostgreSQL, Cloud SQL Connector)
- When extraction query returns 0 results, logs the database URL being queried

**Example logs**:
```
INFO DatabaseManager initialized with URL: postgresql://user:***@localhost:5432/mizzou
INFO Using direct PostgreSQL connection (no Cloud SQL connector)
```

### 4. Database Deduplication and Unique Constraint

**File**: `alembic/versions/1a2b3c4d5e6f_add_unique_constraint_articles_url.py`

Created migration to:
1. Deduplicate existing articles by URL (keeps oldest by `created_at`)
2. Add UNIQUE constraint on `articles.url`
3. Use `CREATE UNIQUE INDEX CONCURRENTLY` for PostgreSQL (no table locks)

**Run migration**:
```bash
# Upgrade to latest schema
alembic upgrade head
```

**Impact**: Prevents duplicate articles at the database level, ensuring data integrity.

### 5. Integration Tests

**File**: `tests/integration/test_extraction_db.py`

Created comprehensive tests to verify:
- Extraction successfully inserts articles
- Post-commit verification works correctly
- Extraction query finds candidate links properly
- ON CONFLICT DO NOTHING handles duplicates
- Extraction query excludes already-processed articles

**Run tests**:
```bash
# Requires TEST_DATABASE_URL environment variable
export TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/test_db"
pytest tests/integration/test_extraction_db.py -v -m integration
```

## Debugging Production Issues

### Check if articles are being written

```sql
-- Check recent article extractions
SELECT COUNT(*), MAX(extracted_at)
FROM articles
WHERE extracted_at > NOW() - INTERVAL '24 hours';

-- Check candidate links waiting for extraction
SELECT COUNT(*)
FROM candidate_links
WHERE status = 'article'
AND id NOT IN (
    SELECT candidate_link_id FROM articles
    WHERE candidate_link_id IS NOT NULL
);
```

### Enable SQL dumping in production

```bash
# In Kubernetes pod or debug container
export EXTRACTION_DUMP_SQL=true
python -m src.cli.cli_modular extract --limit 10 --batches 1
```

This will log:
```
🔍 EXTRACTION_DUMP_SQL enabled - SQL query:
SELECT cl.id, cl.url, cl.source, cl.status, s.canonical_name
FROM candidate_links cl
LEFT JOIN sources s ON cl.source_id = s.id
WHERE cl.status = 'article'
...
Params: {'limit_with_buffer': 30}
```

### Verify database connection

Check the logs for DatabaseManager initialization:
```
INFO DatabaseManager initialized with URL: postgresql://user:***@cloudsql-instance/mizzou
INFO Using Cloud SQL Python Connector
```

If you see SQLite instead of PostgreSQL, the environment variables aren't set correctly.

### Check for post-commit verification failures

Search logs for:
```
❌ POST-COMMIT VERIFICATION FAILED
```

This indicates silent commit failures - articles appear to commit but aren't persisted.

## Environment Variables

### EXTRACTION_DUMP_SQL
- **Type**: Boolean (true/1/yes or false/0/no)
- **Default**: false
- **Purpose**: Log exact SQL queries before execution for debugging
- **Example**: `EXTRACTION_DUMP_SQL=true`

### USE_CLOUD_SQL_CONNECTOR
- **Type**: Boolean
- **Default**: false
- **Purpose**: Use Cloud SQL Python Connector instead of cloud-sql-proxy sidecar
- **Note**: Set to `false` to avoid connector bugs that cause silent commit failures
- **Example**: `USE_CLOUD_SQL_CONNECTOR=false`

### DATABASE_URL
- **Type**: Connection string
- **Purpose**: PostgreSQL connection URL
- **Example**: `postgresql://user:pass@localhost:5432/mizzou`
- **Note**: DatabaseManager logs this (with password masked) on initialization

## Operational Recommendations

### Immediate Actions

1. **Enable post-commit verification** (already done in code)
2. **Run the migration** to add UNIQUE constraint:
   ```bash
   alembic upgrade head
   ```
3. **Monitor logs** for post-commit verification failures
4. **Keep `USE_CLOUD_SQL_CONNECTOR=false`** until connector bug is resolved

### Monitoring

Monitor for these error patterns:

1. **"POST-COMMIT VERIFICATION FAILED"** - Silent commit failure detected
2. **"Extraction query returned 0 candidate articles"** - No candidates found despite DB having them
3. **"Using SQLite database"** when expecting PostgreSQL - Wrong database connection

### Recovery Procedure

If extraction is not writing to database:

1. Check DatabaseManager initialization logs to verify correct database
2. Enable `EXTRACTION_DUMP_SQL=true` and run extraction manually
3. Copy the SQL query from logs and run directly in `psql` to verify it returns rows
4. Check for post-commit verification failures in logs
5. If using Cloud SQL Connector, try disabling it: `USE_CLOUD_SQL_CONNECTOR=false`

## Testing

### Unit Tests
```bash
# Test extraction command imports and basic logic
python -m pytest tests/cli/commands/test_extraction.py -v
```

### Integration Tests
```bash
# Requires PostgreSQL test database
export TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/test_db"
python -m pytest tests/integration/test_extraction_db.py -v -m integration
```

### Manual Testing
```bash
# Test extraction with debugging enabled
export EXTRACTION_DUMP_SQL=true
export LOG_LEVEL=DEBUG
python -m src.cli.cli_modular extract --limit 5 --batches 1
```

## Related Issues

- GitHub Issue #105: Extraction workflow failure and database write issues
- Cloud SQL Python Connector async/await bug (silent commit failures)

## Migration Notes

### Migration 1a2b3c4d5e6f

**Purpose**: Add UNIQUE constraint on `articles.url` and deduplicate existing rows

**Safe for Production**: Yes
- Uses `CREATE UNIQUE INDEX CONCURRENTLY` for PostgreSQL (no table locks)
- Deduplicates before adding constraint (keeps oldest article per URL)
- Handles SQLite, PostgreSQL, and other dialects

**Rollback**: 
```bash
alembic downgrade -1
```

**Verification**:
```sql
-- Check if constraint exists
\d articles  -- PostgreSQL
SELECT sql FROM sqlite_master WHERE type='table' AND name='articles';  -- SQLite

-- Verify no duplicates
SELECT url, COUNT(*) as count
FROM articles
GROUP BY url
HAVING COUNT(*) > 1;
```

## Future Improvements

1. **Idempotent Inserts**: Consider using `ON CONFLICT (url) DO UPDATE` to update existing articles
2. **Batch Verification**: Instead of verifying each article individually, batch verify at end of extraction
3. **Metrics**: Add Prometheus/telemetry metrics for commit verification failures
4. **Alerting**: Alert when post-commit verification fails repeatedly
5. **Retry Logic**: Add automatic retry for silent commit failures
