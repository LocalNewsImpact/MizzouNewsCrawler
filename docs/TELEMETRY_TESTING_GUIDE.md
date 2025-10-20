# Telemetry Testing Guide

This guide explains how to test telemetry code and prevent schema drift issues.

## Quick Start

### Run All Telemetry Tests

```bash
# Run byline telemetry unit tests (SQLite)
pytest tests/utils/test_byline_telemetry.py -v

# Run schema drift detection tests
pytest tests/test_schema_drift_detection.py -v

# Run PostgreSQL integration tests (requires TEST_DATABASE_URL)
TEST_DATABASE_URL="postgresql://user:pass@localhost/test_db" \
  pytest tests/integration/test_byline_telemetry_postgres.py -v
```

### Validate Schema Consistency

```bash
# Quick validation script
python scripts/validate_telemetry_schema.py

# If validation fails, it will show which columns are missing
```

## Background: Why These Tests Exist

**Problem**: Unit tests using SQLite passed, but production PostgreSQL deployments failed due to schema mismatches.

**Root Cause**: 
1. Code's CREATE TABLE had 28 columns
2. Alembic migration created 32 columns in PostgreSQL
3. INSERT statements failed in production due to column count mismatch
4. SQLite tests didn't catch this because they used code's CREATE TABLE

**Solution**: This test suite ensures code and migrations stay in sync.

See [WHY_TESTS_MISSED_TELEMETRY_ERRORS.md](../WHY_TESTS_MISSED_TELEMETRY_ERRORS.md) for detailed analysis.

## Test Categories

### 1. Unit Tests (SQLite)

**File**: `tests/utils/test_byline_telemetry.py`

**Purpose**: Fast tests for basic telemetry functionality

**Database**: SQLite in-memory (created via code's CREATE TABLE)

**Run**: `pytest tests/utils/test_byline_telemetry.py`

**Tests**:
- ✅ Telemetry session persistence
- ✅ Transformation step logging
- ✅ Telemetry disabled mode (no-op)

### 2. Schema Drift Detection Tests

**File**: `tests/test_schema_drift_detection.py`

**Purpose**: Detect schema mismatches between code and Alembic migrations

**Database**: None (parses source files)

**Run**: `pytest tests/test_schema_drift_detection.py`

**Tests**:
- ✅ CREATE TABLE in code matches Alembic migration
- ✅ INSERT column count matches CREATE TABLE
- ✅ All required columns included in INSERT
- ✅ Transformation steps schema matches
- ✅ No stale hardcoded column counts in comments

### 3. PostgreSQL Integration Tests

**File**: `tests/integration/test_byline_telemetry_postgres.py`

**Purpose**: Test against real PostgreSQL with Alembic-migrated schema

**Database**: PostgreSQL (requires `TEST_DATABASE_URL` env var)

**Run**: 
```bash
TEST_DATABASE_URL="postgresql://user:pass@localhost/test_db" \
  pytest tests/integration/test_byline_telemetry_postgres.py
```

**Tests**:
- ✅ INSERT works against Alembic-migrated PostgreSQL
- ✅ Schema column count matches expectations (32 columns)
- ✅ Human review fields can be populated
- ✅ Data integrity across telemetry tables

**Note**: Tests automatically skip if PostgreSQL is not configured.

## Setting Up PostgreSQL Tests

### Option 1: Local PostgreSQL with Docker

```bash
# Start PostgreSQL container
docker run --name postgres-test -e POSTGRES_PASSWORD=test \
  -e POSTGRES_USER=test -e POSTGRES_DB=test_db \
  -p 5432:5432 -d postgres:14

# Run Alembic migrations
export DATABASE_URL="postgresql://test:test@localhost:5432/test_db"
alembic upgrade head

# Run tests
export TEST_DATABASE_URL="postgresql://test:test@localhost:5432/test_db"
pytest tests/integration/test_byline_telemetry_postgres.py -v

# Cleanup
docker stop postgres-test && docker rm postgres-test
```

### Option 2: CI/CD Pipeline

Add to `.github/workflows/ci.yml`:

```yaml
jobs:
  test:
    services:
      postgres:
        image: postgres:14
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_USER: test
          POSTGRES_DB: test_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - name: Run Alembic migrations
        run: alembic upgrade head
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_db
      
      - name: Run PostgreSQL integration tests
        run: pytest tests/integration/test_byline_telemetry_postgres.py -v
        env:
          TEST_DATABASE_URL: postgresql://test:test@localhost:5432/test_db
```

## Validating Schema Changes

### Before Making Schema Changes

1. **Check current state**:
   ```bash
   python scripts/validate_telemetry_schema.py
   ```

2. **Run all tests**:
   ```bash
   pytest tests/test_schema_drift_detection.py tests/utils/test_byline_telemetry.py -v
   ```

### After Making Schema Changes

#### If You Update Code (CREATE TABLE or INSERT)

1. **Update the code**:
   - Modify `src/utils/byline_telemetry.py`
   - Update CREATE TABLE with new columns
   - Update INSERT statement with new columns

2. **Create Alembic migration**:
   ```bash
   alembic revision --autogenerate -m "Add columns to byline_cleaning_telemetry"
   alembic upgrade head
   ```

3. **Validate**:
   ```bash
   python scripts/validate_telemetry_schema.py
   pytest tests/test_schema_drift_detection.py -v
   ```

#### If You Update Alembic Migration

1. **Update the migration file**:
   - Edit migration in `alembic/versions/`
   - Add new columns

2. **Update the code**:
   - Update CREATE TABLE in `src/utils/byline_telemetry.py`
   - Update INSERT statement

3. **Validate**:
   ```bash
   python scripts/validate_telemetry_schema.py
   pytest tests/test_schema_drift_detection.py -v
   ```

## Common Issues and Solutions

### Issue: "Schema drift detected"

**Symptom**: 
```
❌ Schema drift detected!
   Columns in Alembic but not in code: {'human_label', 'human_notes'}
```

**Solution**:
1. Add missing columns to CREATE TABLE in `src/utils/byline_telemetry.py`
2. Add missing columns to INSERT statement
3. Run validation: `python scripts/validate_telemetry_schema.py`

### Issue: "INSERT column count mismatch"

**Symptom**:
```
❌ INSERT statement has issues: INSERT column count (28) does not match 
   CREATE TABLE column count (32)
```

**Solution**:
1. Count columns in CREATE TABLE
2. Update INSERT statement to include all columns
3. Update INSERT values tuple to match column count
4. Run tests: `pytest tests/test_schema_drift_detection.py`

### Issue: PostgreSQL tests fail with "column does not exist"

**Symptom**:
```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedColumn) 
column "human_label" of relation "byline_cleaning_telemetry" does not exist
```

**Solution**:
1. Ensure Alembic migrations are up to date: `alembic upgrade head`
2. Check that PostgreSQL schema matches code: `python scripts/validate_telemetry_schema.py`
3. If needed, regenerate migration: `alembic revision --autogenerate -m "Sync schema"`

## Best Practices

### 1. Always Run Schema Validation Before Commit

```bash
# Add to .git/hooks/pre-commit
#!/bin/bash
python scripts/validate_telemetry_schema.py
if [ $? -ne 0 ]; then
    echo "Schema validation failed. Please fix before committing."
    exit 1
fi
```

### 2. Test Against Both SQLite and PostgreSQL

- SQLite: Fast feedback for basic functionality
- PostgreSQL: Catches production-specific issues

### 3. Keep Schemas in Sync

- **Single source of truth**: Alembic migrations define the production schema
- **Code follows migrations**: UPDATE code CREATE TABLE to match Alembic
- **Automate validation**: Run `validate_telemetry_schema.py` in CI

### 4. Document Schema Changes

When changing schemas:
1. Update code (CREATE TABLE, INSERT)
2. Create Alembic migration
3. Update tests if needed
4. Document reason for change in migration message

### 5. Use ORM for Complex Schemas (Optional)

For tables with >20 columns or frequent changes, consider SQLAlchemy ORM:
- Automatic schema validation
- Type safety
- Easier maintenance
- Less prone to column count errors

## Troubleshooting

### Tests fail locally but pass in CI

**Likely cause**: Different database versions or SQLite vs PostgreSQL

**Solution**: Run PostgreSQL tests locally using Docker (see setup above)

### Schema validation passes but production still fails

**Likely cause**: Production database not migrated

**Solution**: 
1. Check production database: `alembic current`
2. Run migrations: `alembic upgrade head`
3. Verify schema: Connect to production and run `\d byline_cleaning_telemetry`

### Alembic migration conflicts

**Likely cause**: Multiple developers created migrations simultaneously

**Solution**:
1. Pull latest changes: `git pull`
2. Merge migration files or create new one
3. Set dependencies correctly in migration files

## Additional Resources

- [WHY_TESTS_MISSED_TELEMETRY_ERRORS.md](../WHY_TESTS_MISSED_TELEMETRY_ERRORS.md) - Detailed analysis of root causes
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [pytest Documentation](https://docs.pytest.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)

## Quick Reference

| Task | Command |
|------|---------|
| Run unit tests | `pytest tests/utils/test_byline_telemetry.py` |
| Run schema tests | `pytest tests/test_schema_drift_detection.py` |
| Run PostgreSQL tests | `TEST_DATABASE_URL=... pytest tests/integration/test_byline_telemetry_postgres.py` |
| Validate schema | `python scripts/validate_telemetry_schema.py` |
| Create migration | `alembic revision --autogenerate -m "message"` |
| Apply migrations | `alembic upgrade head` |
| Check current migration | `alembic current` |
