# Why Unit Tests Didn't Catch Telemetry Errors

**Date**: October 20, 2025  
**Issue**: `created_at` missing from byline_cleaning_telemetry INSERT

## Root Causes of Test Gaps

### 1. **SQLite vs PostgreSQL Differences**

**The Test:**
```python
# tests/utils/test_byline_telemetry.py
def _make_store(tmp_path):
    return TelemetryStore(
        database=f"sqlite:///{tmp_path / 'byline_telemetry.db'}",  # ❌ SQLite only
        async_writes=False,
    )
```

**The Problem:**
- Tests use **SQLite** which is more permissive
- Production uses **PostgreSQL** which is stricter
- SQLite allows `DEFAULT CURRENT_TIMESTAMP` to work implicitly
- PostgreSQL enforces NOT NULL constraints more strictly

**Schema Drift:**
- `src/utils/byline_telemetry.py` has: `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
- Actual PostgreSQL table (from Alembic migration) has: `created_at` with NOT NULL but no DEFAULT
- Tests create tables with the code definition (has DEFAULT)
- Production uses Alembic migrations (missing DEFAULT)

### 2. **No PostgreSQL Integration Tests for Byline Telemetry**

**What Exists:**
- `tests/test_telemetry_store_postgres.py` - Tests general PostgreSQL compatibility
- `tests/utils/test_byline_telemetry.py` - Tests byline telemetry with SQLite

**What's Missing:**
```python
# ❌ This test doesn't exist
@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
def test_byline_telemetry_postgres_insert(postgres_db_uri):
    """Test byline telemetry INSERT against actual PostgreSQL database."""
    store = TelemetryStore(database=postgres_db_uri, async_writes=False)
    telemetry = BylineCleaningTelemetry(store=store)
    
    telemetry.start_cleaning_session(raw_byline="Test")
    telemetry.finalize_cleaning_session(["Author"], cleaning_method="test")
    telemetry.flush()  # Would fail with constraint violation
```

### 3. **INSERT Statement Not Validated Against Actual Schema**

**The INSERT:**
```python
# src/utils/byline_telemetry.py line 337
INSERT INTO byline_cleaning_telemetry (
    id, article_id, candidate_link_id, source_id,
    source_name, raw_byline, raw_byline_length,
    raw_byline_words, extraction_timestamp,
    cleaning_method, source_canonical_name, final_authors_json,
    final_authors_count, final_authors_display,
    confidence_score, processing_time_ms, has_wire_service,
    has_email, has_title, has_organization,
    source_name_removed, duplicates_removed_count,
    likely_valid_authors, likely_noise,
    requires_manual_review, cleaning_errors,
    parsing_warnings
    -- ❌ Missing: created_at
) VALUES (?, ?, ?, ..., ?)  -- 27 placeholders, should be 28
```

**No Test Validates:**
- Column count matches VALUES placeholder count
- All NOT NULL columns are included
- Column order matches parameter order
- SQL syntax is correct for target database

### 4. **Alembic Migrations Not Tested**

**Migration Files:**
- `alembic/versions/*.py` - Define actual production schema
- Tests create tables using `CREATE TABLE IF NOT EXISTS` in code
- Production tables created by Alembic may differ from code

**Gap:**
```python
# Code says:
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

# But Alembic migration might have:
op.add_column('byline_cleaning_telemetry',
    sa.Column('created_at', sa.TIMESTAMP(), nullable=False))  # No default!
```

### 5. **No SQL Linting/Validation**

**What's Missing:**
- No static analysis of SQL statements
- No validation of placeholder count vs parameter count
- No schema drift detection between code and migrations
- No check that INSERT includes all NOT NULL columns

## How These Issues Manifested

### Test Environment (SQLite)
✅ **Passes** because:
1. Table created with `DEFAULT CURRENT_TIMESTAMP`
2. SQLite implicitly uses default when column omitted
3. No constraint violation

### Production Environment (PostgreSQL)
❌ **Fails** because:
1. Table created by Alembic without default
2. INSERT omits `created_at` column
3. PostgreSQL enforces NOT NULL constraint
4. Error: `null value in column "created_at" violates not-null constraint`

## Recommendations to Prevent Future Issues

### 1. **Add PostgreSQL Integration Tests**

```python
# tests/utils/test_byline_telemetry_postgres.py
import pytest
from src.utils.byline_telemetry import BylineCleaningTelemetry
from src.telemetry.store import TelemetryStore

POSTGRES_URL = os.getenv("TEST_DATABASE_URL")
HAS_POSTGRES = POSTGRES_URL and "postgres" in POSTGRES_URL

@pytest.mark.skipif(not HAS_POSTGRES, reason="PostgreSQL not configured")
def test_byline_telemetry_full_workflow_postgres():
    """Test complete byline telemetry workflow against PostgreSQL."""
    store = TelemetryStore(database=POSTGRES_URL, async_writes=False)
    telemetry = BylineCleaningTelemetry(store=store)
    
    # Test actual INSERT path that production uses
    telemetry_id = telemetry.start_cleaning_session(
        raw_byline="By John Doe",
        article_id="test-article",
        candidate_link_id="test-link",
        source_id="test-source",
        source_name="Test Source"
    )
    
    telemetry.finalize_cleaning_session(
        ["John Doe"],
        cleaning_method="standard_pipeline"
    )
    
    # This would catch the missing created_at error
    telemetry.flush()
    
    # Verify data was inserted correctly
    with store.connection() as conn:
        result = conn.execute(
            "SELECT created_at FROM byline_cleaning_telemetry WHERE id = %s",
            (telemetry_id,)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] is not None  # created_at should be set
```

### 2. **Run Tests Against Production Database Schema**

```bash
# CI/CD pipeline
# 1. Spin up PostgreSQL container
docker run -d --name test-postgres -e POSTGRES_PASSWORD=test postgres:14

# 2. Run Alembic migrations (production schema)
TEST_DATABASE_URL=postgresql://postgres:test@localhost/test alembic upgrade head

# 3. Run tests against migrated schema
TEST_DATABASE_URL=postgresql://postgres:test@localhost/test pytest tests/
```

### 3. **Add SQL Validation Tools**

```python
# tests/test_sql_validation.py
def test_insert_statements_match_schema():
    """Validate all INSERT statements include required columns."""
    # Parse INSERT statements from code
    # Compare against actual table schema
    # Verify column count, NOT NULL columns included, etc.
```

### 4. **Add Schema Drift Detection**

```python
# tests/test_schema_consistency.py
def test_code_tables_match_alembic_migrations():
    """Ensure CREATE TABLE in code matches Alembic migrations."""
    # Compare table definitions in code vs migrations
    # Detect drift (missing defaults, wrong types, etc.)
```

### 5. **Use SQLAlchemy ORM Instead of Raw SQL**

```python
# Instead of:
cursor.execute("INSERT INTO table (col1, col2) VALUES (?, ?)", (val1, val2))

# Use ORM:
from sqlalchemy import insert
stmt = insert(BylineCleaningTelemetry).values(
    id=telemetry_id,
    article_id=article_id,
    # ... all columns including created_at
    created_at=datetime.utcnow()
)
conn.execute(stmt)
```

**Benefits:**
- Type checking at development time
- Automatic validation of column names
- Can't forget required columns
- Database-agnostic parameter binding

### 6. **Add Pre-Commit Hooks**

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
  - id: sql-lint
    name: SQL Linter
    entry: sqlfluff lint
    language: python
    files: \\.py$
    
  - id: placeholder-count
    name: Validate SQL Placeholder Count
    entry: python scripts/validate_sql.py
    language: python
    files: \\.py$
```

## Lessons Learned

1. **Test against production database engine** - SQLite is not sufficient
2. **Integration tests matter** - Unit tests with mocks miss real issues
3. **Schema drift is dangerous** - Code and migrations must stay in sync
4. **Raw SQL is error-prone** - Consider ORM for type safety
5. **CI/CD should use production schema** - Run Alembic migrations in tests

## Similar Issues to Check

These telemetry modules likely have the same pattern:

- ✅ `src/utils/byline_telemetry.py` - Fixed (fe9659f)
- ⚠️ `src/utils/content_cleaning_telemetry.py` - Check for missing columns
- ⚠️ `src/utils/extraction_telemetry.py` - Check for missing columns
- ⚠️ `src/utils/comprehensive_telemetry.py` - Already fixed proxy issues
- ⚠️ `src/telemetry/store.py` - General store, likely OK

**Action**: Audit all telemetry INSERT statements for missing columns.
