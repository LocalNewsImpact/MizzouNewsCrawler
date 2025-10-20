# Analysis: Why Unit Tests Missed Telemetry Errors

**Date**: October 2025  
**Issue**: Byline telemetry INSERT statements failed in PostgreSQL production but passed in SQLite tests

## Executive Summary

Unit tests for byline telemetry passed successfully in the CI/CD pipeline using SQLite, but the same code failed in production PostgreSQL databases with schema mismatch errors. This document analyzes why the tests failed to catch these errors and provides recommendations to prevent similar issues in the future.

## Root Causes Identified

### 1. SQLite vs PostgreSQL: Different Schema Constraints

**Problem**: Tests use SQLite in-memory databases while production uses PostgreSQL (via Cloud SQL). SQLite is more permissive with schema violations than PostgreSQL.

**Evidence**:
- Test configuration: `TelemetryStore(database="sqlite:///:memory:", async_writes=False)`
- Production configuration: PostgreSQL via Cloud SQL Connector
- SQLite allows schema mismatches that PostgreSQL rejects

**Impact**: Column count mismatches and data type issues that fail in PostgreSQL may pass silently in SQLite.

### 2. Schema Drift Between Code and Alembic Migrations

**Problem**: The `CREATE TABLE` statement in `src/utils/byline_telemetry.py` differs from the Alembic migration schema in PostgreSQL.

**Evidence**:
```python
# Code CREATE TABLE (byline_telemetry.py): 28 columns
CREATE TABLE IF NOT EXISTS byline_cleaning_telemetry (
    id, article_id, candidate_link_id, source_id, source_name, raw_byline,
    raw_byline_length, raw_byline_words, extraction_timestamp, cleaning_method,
    source_canonical_name, final_authors_json, final_authors_count,
    final_authors_display, confidence_score, processing_time_ms, has_wire_service,
    has_email, has_title, has_organization, source_name_removed,
    duplicates_removed_count, likely_valid_authors, likely_noise,
    requires_manual_review, cleaning_errors, parsing_warnings, created_at
)

# Alembic migration (e3114395bcc4): 32 columns
# Additional columns: human_label, human_notes, reviewed_by, reviewed_at
```

**Impact**: 
- INSERT statements in code expect 28 columns
- PostgreSQL tables (created via Alembic) have 32 columns
- Column mismatch causes INSERT failures in production

### 3. No PostgreSQL Integration Tests for Byline Telemetry

**Problem**: No integration tests validate telemetry code against PostgreSQL databases with Alembic-migrated schemas.

**Evidence**:
- `tests/utils/test_byline_telemetry.py` only uses SQLite fixtures
- No tests run against PostgreSQL with Alembic migrations
- Tests create schema using code's CREATE TABLE, not Alembic

**Impact**: Schema drift and PostgreSQL-specific issues go undetected until production deployment.

### 4. No Validation of INSERT Statement Column Counts

**Problem**: No automated validation ensures INSERT column counts match table schemas.

**Evidence**:
- INSERT statement manually lists 28 columns and 28 placeholders
- No runtime or compile-time checks verify column count matches schema
- Schema changes in migrations don't trigger INSERT statement updates

**Impact**: Schema changes break INSERT statements silently, caught only in production.

### 5. Raw SQL More Error-Prone Than ORM

**Problem**: Manual SQL construction is prone to human error and doesn't benefit from ORM type safety.

**Evidence**:
```python
# Current approach: Manual SQL with ? placeholders
cursor.execute("""
    INSERT INTO byline_cleaning_telemetry (
        id, article_id, candidate_link_id, ...  # 28 columns listed manually
    ) VALUES (?, ?, ?, ...)  # 28 placeholders counted manually
""", (value1, value2, value3, ...))  # 28 values passed manually
```

**Impact**: 
- Easy to miss columns when schema changes
- No compile-time or runtime validation
- Maintenance burden increases with schema complexity

## Why Tests Passed in CI But Failed in Production

### Test Environment
1. **SQLite in-memory database**: Created by code's CREATE TABLE (28 columns)
2. **Schema source**: Code's CREATE TABLE IF NOT EXISTS
3. **INSERT target**: SQLite table with 28 columns
4. **Result**: ✅ INSERT with 28 columns succeeds

### Production Environment
1. **PostgreSQL database**: Created by Alembic migration (32 columns)
2. **Schema source**: Alembic migration `e3114395bcc4`
3. **INSERT target**: PostgreSQL table with 32 columns
4. **Result**: ❌ INSERT with 28 columns fails (missing required columns or column count mismatch)

## Timeline of How This Happened

1. **Initial implementation**: Byline telemetry created with 28-column schema
2. **Alembic migration added**: Migration `e3114395bcc4` created with 32 columns (added human review fields)
3. **Code not updated**: `byline_telemetry.py` still uses original 28-column schema
4. **Tests passed**: Tests use code's 28-column schema, consistent with INSERT
5. **Production failed**: PostgreSQL uses Alembic's 32-column schema, INSERT column count mismatch

## Recommendations

### Priority 1: Fix Schema Drift (COMPLETED)

**Action**: Update `byline_telemetry.py` to match Alembic migration schema.

**Changes Made**:
- ✅ Updated CREATE TABLE to include `human_label`, `human_notes`, `reviewed_by`, `reviewed_at`
- ✅ Updated INSERT statement to include all 32 columns
- ✅ Verified tests still pass with updated schema

### Priority 2: Add PostgreSQL Integration Tests

**Action**: Create integration tests that run against PostgreSQL with Alembic-migrated schemas.

**Implementation**:
```python
# tests/integration/test_byline_telemetry_postgres.py
import pytest
from alembic import command
from alembic.config import Config

@pytest.fixture
def postgres_with_alembic(postgresql_db):
    """PostgreSQL database with Alembic-migrated schema."""
    # Run Alembic migrations
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    return postgresql_db

@pytest.mark.integration
def test_byline_telemetry_insert_postgres(postgres_with_alembic):
    """Verify byline telemetry INSERT works against Alembic-migrated PostgreSQL."""
    from src.utils.byline_telemetry import BylineCleaningTelemetry
    
    telemetry = BylineCleaningTelemetry(
        store=TelemetryStore(database=postgres_with_alembic, async_writes=False)
    )
    
    # Run full telemetry workflow
    telemetry_id = telemetry.start_cleaning_session(...)
    telemetry.log_transformation_step(...)
    telemetry.finalize_cleaning_session(...)
    telemetry.flush()
    
    # Verify data was inserted successfully
    assert telemetry was stored correctly
```

### Priority 3: Add Schema Drift Detection

**Action**: Create automated checks to detect schema drift between code and Alembic migrations.

**Implementation**:
```python
# tests/test_schema_drift.py
def test_byline_telemetry_schema_matches_alembic():
    """Verify byline_telemetry.py CREATE TABLE matches Alembic migration."""
    # Parse CREATE TABLE from code
    code_columns = extract_columns_from_code("src/utils/byline_telemetry.py")
    
    # Parse schema from Alembic migration
    alembic_columns = extract_columns_from_migration(
        "alembic/versions/e3114395bcc4_*.py"
    )
    
    # Assert schemas match
    assert code_columns == alembic_columns, (
        f"Schema drift detected!\n"
        f"Code columns: {code_columns}\n"
        f"Alembic columns: {alembic_columns}\n"
        f"Missing in code: {alembic_columns - code_columns}\n"
        f"Missing in Alembic: {code_columns - alembic_columns}"
    )
```

### Priority 4: Add SQL Validation

**Action**: Add runtime validation of INSERT column counts.

**Implementation**:
```python
def validate_insert_columns(table_name, insert_columns, values):
    """Validate INSERT column count matches value count and table schema."""
    # Check column count matches value count
    if len(insert_columns) != len(values):
        raise ValueError(
            f"Column count mismatch: {len(insert_columns)} columns "
            f"but {len(values)} values"
        )
    
    # Query actual table schema
    actual_columns = get_table_columns(table_name)
    
    # Check for missing required columns
    missing = set(actual_columns) - set(insert_columns)
    if missing:
        raise ValueError(
            f"Missing required columns in INSERT: {missing}"
        )
```

### Priority 5: Migrate to SQLAlchemy ORM (Future Enhancement)

**Action**: Replace raw SQL with SQLAlchemy ORM for type safety and automatic schema validation.

**Benefits**:
- Type safety at development time
- Automatic column validation
- Easier maintenance
- Better IDE support
- Automatic migration generation

**Example**:
```python
# Define ORM model
class BylineCleaningTelemetry(Base):
    __tablename__ = 'byline_cleaning_telemetry'
    
    id = Column(String, primary_key=True)
    article_id = Column(String)
    # ... all columns defined with types
    
# Insert using ORM (automatic column validation)
session.add(BylineCleaningTelemetry(
    id=telemetry_id,
    article_id=article_id,
    # ... SQLAlchemy validates all required columns exist
))
session.commit()
```

## Testing Best Practices Going Forward

### 1. Test Against Production Database Type

**Always test against the same database type used in production:**
- If production uses PostgreSQL, run integration tests against PostgreSQL
- SQLite tests are fine for unit tests, but add PostgreSQL integration tests
- Use Docker containers for local PostgreSQL testing

### 2. Use Alembic-Migrated Schemas in Tests

**Create test schemas using Alembic, not code CREATE TABLE:**
```python
@pytest.fixture
def test_db_with_alembic():
    """Test database with production-like schema."""
    # Run Alembic migrations to create schema
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    return database
```

### 3. Detect Schema Drift Automatically

**Add CI checks for schema drift:**
- Parse schemas from code and migrations
- Compare and fail if they don't match
- Run on every PR to catch drift early

### 4. Validate SQL at Runtime

**Add validation for critical SQL operations:**
- Check INSERT column counts match table schema
- Validate required columns are present
- Log warnings for potential issues

### 5. Consider ORM for Complex Schemas

**Use SQLAlchemy ORM for tables with:**
- Many columns (>20)
- Frequent schema changes
- Complex relationships
- Need for type safety

## Metrics to Track

To prevent similar issues in the future, track:

1. **Schema Drift Incidents**: Number of production failures due to schema mismatches (Target: 0)
2. **PostgreSQL Integration Test Coverage**: % of telemetry code tested against PostgreSQL (Target: 80%)
3. **Alembic Migration Coverage**: % of tests using Alembic-migrated schemas (Target: 100% for integration tests)
4. **SQL Validation Coverage**: % of INSERT/UPDATE statements with validation (Target: 100% for critical tables)

## Conclusion

The root cause of telemetry errors reaching production was **not inadequate testing**, but rather **testing against the wrong database schema**. Tests passed because they used SQLite with a 28-column schema created by code, while production used PostgreSQL with a 32-column schema created by Alembic migrations.

**Key Takeaways**:
1. ✅ Test against the same database type and schema source as production
2. ✅ Detect and prevent schema drift between code and migrations
3. ✅ Add validation for SQL operations with manual column lists
4. ✅ Consider ORM for complex schemas requiring frequent changes
5. ✅ Use integration tests with Alembic migrations, not just unit tests with SQLite

**Status**: Schema drift has been fixed, and recommendations have been documented. Implementation of PostgreSQL integration tests and schema drift detection is pending.
