# SQLite to PostgreSQL Migration - Comprehensive Audit

**Date**: 2025-11-03  
**Goal**: Migrate ALL testing and production code away from SQLite to PostgreSQL exclusively

## Executive Summary

**CRITICAL FINDINGS**:
- **21 test files** use in-memory SQLite (`sqlite:///:memory:`)
- **Pipeline-integral components** (telemetry, discovery, extraction, verification) have tests using SQLite
- **E2E tests** all use SQLite, representing INCORRECT production behavior
- **Integration job** in CI still uses SQLite despite having a `postgres-integration` job

## Categories of Tests Using SQLite

### ❌ CRITICAL: Pipeline-Integral Tests (MUST MIGRATE)

These tests touch core pipeline components and MUST use PostgreSQL:

1. **Telemetry Tests** (Pipeline-Critical)
   - `tests/test_telemetry_integration.py` - Uses SQLite, but telemetry is pipeline-critical ❌
   - `tests/test_telemetry_store.py` - Unit test for TelemetryStore, could argue for SQLite ⚠️
   - `tests/test_telemetry_database_resolution.py` - Tests DB resolution logic ⚠️
   - `tests/test_rss_telemetry_integration.py` - RSS + telemetry integration ❌
   - `tests/utils/test_content_cleaning_telemetry.py` - Content cleaning with telemetry ❌
   - `tests/utils/test_byline_telemetry.py` - Byline extraction with telemetry ❌

2. **Discovery Tests** (Pipeline-Critical)
   - `tests/crawler/test_discovery_helpers.py` - Discovery helper functions ❌
   - `tests/crawler/test_discovery_process_source.py` - Source processing ❌
   - `tests/crawler/test_discovery_sqlite_compat.py` - **EXPLICITLY tests SQLite compat** ❌❌❌
   - `tests/test_simple_discovery.py` - Basic discovery flow ❌

3. **Extraction Tests** (Pipeline-Critical)
   - `tests/test_extraction_command.py` - Extraction CLI command ❌
   - `tests/test_entity_extraction_command.py` - Entity extraction ❌
   - `tests/pipeline/test_entity_extraction.py` - Entity extraction pipeline ❌

4. **E2E Tests** (Pipeline-Critical - ALL MUST USE POSTGRES)
   - `tests/e2e/test_county_pipeline_golden_path.py` - Uses SQLite ❌❌❌
   - `tests/e2e/test_discovery_pipeline.py` - Uses SQLite ❌❌❌
   - `tests/e2e/test_extraction_analysis_pipeline.py` - Uses SQLite ❌❌❌

5. **Other Pipeline Tests**
   - `tests/backfill/test_backfill_article_entities.py` - Article entity backfill ❌
   - `tests/test_get_sources_params_and_integration.py` - Source integration ❌
   - `tests/test_scheduling.py` - Scheduling logic ❌
   - `tests/test_prioritization.py` - Prioritization logic ❌

### ⚠️ EVALUATE: Possibly Acceptable SQLite Usage

These might be acceptable to keep as SQLite for fast unit tests:

6. **Pure Unit Tests** (No Production Behavior)
   - `tests/test_config_db_layering.py` - Config layering logic only
   - `tests/test_geocode_cache.py` - Geocoding cache logic
   - `tests/test_pg8000_params.py` - Parameter handling tests
   - `tests/utils/test_dataset_utils.py` - Dataset utility functions

7. **Test Infrastructure**
   - `tests/backend/conftest.py` - Provides fixtures (has cloud_sql_session too)
   - `tests/conftest.py` - Forces SQLite for all tests by default ❌❌❌

### ✅ ALREADY USING POSTGRES

These tests are correctly using PostgreSQL:

8. **Integration Tests** (All in `tests/integration/`)
   - `test_byline_telemetry_postgres.py` ✅
   - `test_cloud_sql_connection.py` ✅
   - `test_discovery_postgres.py` ✅
   - `test_pipeline_critical_sql.py` ✅
   - `test_pipeline_status_command_postgres.py` ✅
   - `test_telemetry_command_postgres.py` ✅
   - `test_telemetry_postgres_type_handling.py` ✅
   - `test_telemetry_retry_postgres.py` ✅
   - `test_verification_command_postgres.py` ✅
   - `test_verification_telemetry_postgres.py` ✅

## Source Code Findings

### Database Connection Code

**File**: `src/models/database.py` (1694 lines)
- **162 references to "sqlite"** in src/ directory
- Contains extensive SQLite compatibility code:
  - `_configure_sqlite_engine()` - WAL mode, PRAGMA statements
  - `safe_execute()` - Handles qmark/printf parameter styles for SQLite
  - `safe_session_execute()` - Session-level parameter compatibility
  - `_ConnectionProxy` and `_EngineProxy` - Connection wrapping for SQLite
  - SQLite-specific trigger creation for UUID generation
  - Dialect detection branches throughout

### Critical Type Handling Issue

**Problem**: PostgreSQL (via pg8000) returns aggregate results as strings
- `.scalar() or 0` patterns FAIL because string "0" is truthy
- Found in: `src/cli/commands/extraction.py:487`
- Likely many more in status/reporting commands

### Test Configuration

**File**: `tests/conftest.py`
```python
# Lines 7-22: FORCES SQLITE FOR ALL TESTS
if "USE_CLOUD_SQL_CONNECTOR" not in os.environ:
    os.environ["USE_CLOUD_SQL_CONNECTOR"] = "false"
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
```

This is the ROOT CAUSE of SQLite usage in tests!

### CI Configuration

**File**: `.github/workflows/ci.yml`

1. **unit job** (line 153): Uses SQLite in-memory ⚠️
2. **argo-quick job** (line 194): Uses SQLite in-memory ⚠️
3. **origin-proxy-only job** (line 236): Uses SQLite in-memory ⚠️
4. **postgres-integration job** (line 277): ✅ Uses PostgreSQL 15
5. **integration job** (line 372): ❌ Uses SQLite - SHOULD USE POSTGRES

## Migration Strategy

### Phase 1: Critical Test Infrastructure Changes (FOUNDATION)

**Priority**: HIGHEST  
**Goal**: Make PostgreSQL the default for all tests

1. **Update `tests/conftest.py`** ❌ CRITICAL
   - Remove SQLite defaults
   - Make PostgreSQL the default database
   - Provide PostgreSQL fixtures for all tests
   - Only allow SQLite opt-in for specific unit tests

2. **Update `pytest.ini`** ❌ CRITICAL
   - Change default markers
   - Update test discovery patterns
   - Configure PostgreSQL as default

3. **Update CI Jobs** ❌ CRITICAL
   - Migrate `integration` job to use PostgreSQL
   - Keep `unit` job but evaluate which tests should migrate
   - Ensure all jobs have PostgreSQL services

### Phase 2: Migrate Pipeline-Critical Tests (HIGH PRIORITY)

**All tests touching telemetry, discovery, extraction, verification, e2e**

1. **Telemetry Tests**
   - Convert `test_telemetry_integration.py` to PostgreSQL
   - Convert `test_rss_telemetry_integration.py` to PostgreSQL
   - Convert content cleaning telemetry tests
   - Convert byline telemetry tests

2. **Discovery Tests**
   - Convert all `tests/crawler/test_discovery_*.py` to PostgreSQL
   - **DELETE** `test_discovery_sqlite_compat.py` entirely
   - Convert `test_simple_discovery.py` to PostgreSQL

3. **Extraction Tests**
   - Convert `test_extraction_command.py` to PostgreSQL
   - Convert `test_entity_extraction_command.py` to PostgreSQL
   - Convert `test_entity_extraction.py` to PostgreSQL

4. **E2E Tests** (CRITICAL - These represent production)
   - Convert `test_county_pipeline_golden_path.py` to PostgreSQL
   - Convert `test_discovery_pipeline.py` to PostgreSQL
   - Convert `test_extraction_analysis_pipeline.py` to PostgreSQL

5. **Other Pipeline Tests**
   - Backfill tests
   - Source integration tests
   - Scheduling and prioritization tests

### Phase 3: Source Code Cleanup (AFTER TESTS WORK)

**Priority**: HIGH (but after tests are migrated)

1. **Remove SQLite Support from `database.py`**
   - Remove `_configure_sqlite_engine()`
   - Remove `safe_execute()` and `safe_session_execute()`
   - Remove `_ConnectionProxy` and `_EngineProxy`
   - Remove SQLite trigger creation
   - Simplify `DatabaseManager.__init__()`

2. **Remove SQLite Support from `telemetry/store.py`**
   - Remove SQLite PRAGMA statements
   - Simplify DDL adaptation

3. **Fix Aggregate Type Handling** (CRITICAL FOR PRODUCTION)
   - Add type conversion helpers
   - Fix all `.scalar() or 0` patterns
   - Fix row tuple indexing with aggregates
   - Add tests for type handling

### Phase 4: Final Validation

1. **CI Validation**
   - All jobs green with PostgreSQL
   - No SQLite references in test runs
   - Code coverage maintained

2. **Integration Testing**
   - Run full test suite against PostgreSQL
   - Manual CLI command testing
   - Performance validation

3. **Documentation**
   - Update README
   - Update developer guides
   - Migration guide for contributors

## Test Migration Pattern

### Standard Pattern for Converting Tests to PostgreSQL

```python
# OLD (SQLite)
@pytest.fixture
def test_db(tmp_path):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    return DatabaseManager(database_url=db_url)

# NEW (PostgreSQL)
@pytest.mark.integration
@pytest.mark.postgres
def test_something(cloud_sql_session):
    """Test with PostgreSQL using transactional isolation."""
    # cloud_sql_session provides automatic rollback
    # No cleanup needed
    pass
```

### For E2E Tests

```python
# OLD (SQLite)
def test_e2e_pipeline(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    def manager_factory(*args, **kwargs):
        return DatabaseManager(database_url=db_url)
    monkeypatch.setattr(module, "DatabaseManager", manager_factory)
    # ... test code

# NEW (PostgreSQL)
@pytest.mark.integration
@pytest.mark.postgres
def test_e2e_pipeline(cloud_sql_engine, monkeypatch):
    """E2E test with PostgreSQL (production-like)."""
    def manager_factory(*args, **kwargs):
        return DatabaseManager(database_url=str(cloud_sql_engine.url))
    monkeypatch.setattr(module, "DatabaseManager", manager_factory)
    # ... test code
```

## Metrics

### Current State
- **Total test files**: ~150
- **Tests using SQLite**: ~40+
- **Pipeline-critical tests using SQLite**: ~25
- **SQLite references in src/**: 162

### Target State
- **Tests using SQLite**: 0-5 (only isolated unit tests)
- **Pipeline-critical tests using PostgreSQL**: 100%
- **SQLite references in src/**: <20 (only for migration/legacy support)

## Risk Assessment

### HIGH RISK Areas
1. E2E tests using SQLite - represent incorrect production behavior
2. Telemetry tests using SQLite - telemetry is production-critical
3. `tests/conftest.py` forcing SQLite - affects all tests

### MEDIUM RISK Areas
1. Type handling issues with PostgreSQL aggregates
2. CI job configurations
3. Test execution time increase

### LOW RISK Areas
1. Pure unit tests (can keep SQLite)
2. Documentation updates
3. Code cleanup

## Success Criteria

✅ All pipeline-critical tests use PostgreSQL  
✅ All E2E tests use PostgreSQL  
✅ CI `integration` job uses PostgreSQL  
✅ No `.scalar() or 0` patterns in production code  
✅ All tests pass with PostgreSQL  
✅ Code coverage maintained (78%+)  
✅ No SQLite compatibility code in DatabaseManager  
✅ Production deployment succeeds with no DB errors

## Timeline Estimate

- **Phase 1** (Infrastructure): 4-6 hours
- **Phase 2** (Test Migration): 12-16 hours
- **Phase 3** (Source Cleanup): 6-8 hours
- **Phase 4** (Validation): 4-6 hours

**Total**: ~26-36 hours of focused work

## Next Actions

1. ✅ Complete this audit (DONE)
2. Update `tests/conftest.py` to use PostgreSQL by default
3. Set up local PostgreSQL for testing
4. Migrate first batch of telemetry tests
5. Validate test migrations work
6. Continue systematic migration
