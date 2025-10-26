# Test Infrastructure Fixes Required for Cloud SQL Migration

## Problem Summary

After the Cloud SQL migration, **103 out of 966 tests** are failing or erroring (10.7%). The test suite needs systematic updates to align with the new Cloud SQL infrastructure, fix Alembic migration conflicts, and update test expectations for the modernized telemetry system.

**Test Results:**
- ✅ **863 passed** (89.3%)
- ❌ **61 failed** (6.3%)
- ⚠️ **33 errors** (3.4%)
- ⏭️ **9 skipped** (0.9%)
- **Total**: 966 tests

## Problem Categories

### 1. Cloud SQL Connector Missing (33 errors) 🔴

**Issue:** Tests fail with `ModuleNotFoundError: No module named 'google.cloud.sql.connector'`

**Root Cause:** The `DatabaseManager` class attempts to use Cloud SQL connector when `USE_CLOUD_SQL_CONNECTOR` is set, but the connector is not available in the test environment.

**Affected Areas:**
- E2E tests (`tests/e2e/`)
- Integration tests (`tests/*/test_*_integration.py`)
- Reporting tests (`tests/reporting/`)
- CLI command tests requiring database access

### 2. Alembic Migration Conflicts (11 failures) 🔴

**Issue:** Multiple migrations try to create the same `byline_cleaning_telemetry` table, causing "table already exists" errors.

**Root Cause:** Two separate migrations both create the `byline_cleaning_telemetry` table:
- `e3114395bcc4_add_api_backend_and_telemetry_tables.py` (earlier migration)
- `a9957c3054a4_add_remaining_telemetry_tables.py` (later migration)

**Example Error:**
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) table byline_cleaning_telemetry already exists
```

**Affected:** All 11 tests in `tests/alembic/test_alembic_migrations.py`

### 3. Integration Tests Requiring Cloud SQL Connector (12 failures) 🟡

**Issue:** Integration tests that connect to databases fail because they can't initialize `DatabaseManager`.

**Root Cause:** Tests pass SQLite URLs but `DatabaseManager` tries to use Cloud SQL connector first, which requires:
- `google-cloud-sql-python-connector` package
- Valid GCP credentials
- Network access to Cloud SQL instance

**Affected Test Files:**
- `tests/test_get_sources_params_and_integration.py`
- `tests/crawler/test_discovery_integration.py`
- `tests/services/test_gazetteer_service.py`
- `tests/backfill/test_backfill_article_entities.py`
- `tests/pipeline/test_extraction_pipeline_integration.py`

### 4. Telemetry Tests with Outdated Expectations (5 failures) 🟡

**Issue:** Tests expect old CSV-based data or outdated API response formats after migration to Cloud SQL.

**Examples:**
- `test_telemetry_summary_endpoint` - Expected 5 extractions, got 106
- `test_http_errors_endpoint` - Expected ≥2 errors, got 1
- `test_track_http_status_inserts_row` - Missing `status_category` parameter
- `test_operation_tracker.py` - Tests passing raw file paths instead of `sqlite:///` URLs

### 5. Missing MAIN_DB_PATH Constant (12 failures) 🟡

**Issue:** Tests try to patch `backend.app.main.MAIN_DB_PATH` which was removed during Cloud SQL migration.

**Root Cause:** The backend migrated from using a hardcoded `MAIN_DB_PATH` constant to using `DatabaseManager`. Tests still reference the old constant.

---

## Roadmap to Fix

### Phase 1: Environment and Dependencies (Week 1) 🔴 HIGH PRIORITY

**Goal:** Ensure test environment can run all tests without import errors.

#### Tasks:
- [ ] Add `google-cloud-sql-python-connector` to `requirements-dev.txt`
- [ ] Create `DatabaseManager` test fixture that forces SQLite mode
- [ ] Add mock Cloud SQL connector for tests that don't need real connections
- [ ] Update environment variable override in test setup

**Implementation:**
```python
# tests/conftest.py
@pytest.fixture
def test_database_manager(tmp_path, monkeypatch):
    """Create DatabaseManager with SQLite for testing."""
    monkeypatch.setenv("USE_CLOUD_SQL_CONNECTOR", "false")
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    
    dbm = DatabaseManager(database_url=db_url)
    yield dbm
    dbm.close()
```

**Target:** 33 errors → 0

### Phase 2: Fix Alembic Migration Conflicts (Week 1-2) 🔴 CRITICAL

**Goal:** Resolve duplicate table creation in migrations.

#### Tasks:
- [ ] Audit all tables created by each migration
- [ ] Remove duplicate `byline_cleaning_telemetry` creation from later migration
- [ ] Test fresh database: `alembic upgrade head`
- [ ] Test downgrade: `alembic downgrade -1`
- [ ] Test upgrade again: `alembic upgrade head`

**Recommended Approach:** Remove duplicate from `a9957c3054a4_add_remaining_telemetry_tables.py`

**Target:** 11 failures → 0

### Phase 3: Fix Integration Tests (Week 2) 🟡

**Goal:** All integration tests pass with SQLite backend.

#### Tasks:
- [ ] Replace direct `DatabaseManager()` calls with test fixture
- [ ] Ensure all tests use `monkeypatch` to disable Cloud SQL
- [ ] Fix URL format: always use `sqlite:///path`
- [ ] Replace `@patch("backend.app.main.MAIN_DB_PATH")` with `@patch("backend.app.main.db_manager")`

**Pattern:**
```python
# Before
def test_something(tmp_path):
    db_url = str(tmp_path / "test.db")  # Wrong format
    dbm = DatabaseManager(database_url=db_url)  # May try Cloud SQL

# After
def test_something(test_database_manager):
    dbm = test_database_manager  # Already configured with SQLite
```

**Target:** 12 failures → 0

### Phase 4: Fix Telemetry Test Expectations (Week 2-3) 🟡

**Goal:** Align test expectations with Cloud SQL schema and data.

#### Tasks:
- [ ] Create comprehensive test data fixtures that match production schema
- [ ] Update API response assertions to match reality
- [ ] Fix field name mismatches (e.g., `reviewed_by` → `reviewer`)
- [ ] Add missing parameters (e.g., `status_category`)
- [ ] Fix URL format in `TelemetryStore` initialization

**Example Fix:**
```python
# Add auto-derive status_category if not provided
def track_http_status(..., status_category: str | None = None):
    if status_category is None:
        if 200 <= status_code < 300:
            status_category = "2xx"
        elif 400 <= status_code < 500:
            status_category = "4xx"
        # ... etc
```

**Target:** 5 failures → 0

### Phase 5: Create E2E Test Suite (Week 3-4) 🟢

**Goal:** Comprehensive end-to-end tests that work with Cloud SQL schema.

#### Test Scenarios:
1. **Discovery → Extraction → Analysis → Telemetry**
2. **Failed Extraction Recovery**
3. **Duplicate Detection**

#### Tasks:
- [ ] Create shared E2E fixtures
- [ ] Migrate existing E2E tests to use new fixtures
- [ ] Add new E2E tests for Cloud SQL features
- [ ] Verify tests pass in CI/CD

### Phase 6: Documentation and CI/CD (Week 4) 🟢

**Goal:** Document testing approach and integrate into CI/CD.

#### Tasks:
- [ ] Create testing best practices guide
- [ ] Document how to run tests locally
- [ ] Update CI/CD pipeline with test database setup
- [ ] Add test result reporting
- [ ] Set minimum coverage threshold

---

## Test Coverage Plan

### Current Coverage Analysis

**Well-Tested Areas (>90% coverage):**
- ✅ Core discovery logic
- ✅ Content extraction
- ✅ Entity extraction
- ✅ Telemetry store
- ✅ Configuration management

**Under-Tested Areas (<70% coverage):**
- ⚠️ Database migrations - Currently 0% due to conflicts
- ⚠️ Cloud SQL connector integration
- ⚠️ API endpoint error handling
- ⚠️ Telemetry aggregation queries

### Coverage Goals

| Area | Current | Target | Priority |
|------|---------|--------|----------|
| Core Discovery | 95% | 95% | ✅ Maintain |
| Extraction | 92% | 95% | 🔼 Improve |
| Telemetry | 88% | 95% | 🔼 Improve |
| Database Layer | 65% | 85% | 🔼🔼 High |
| API Endpoints | 80% | 90% | 🔼 Improve |
| Alembic Migrations | 0% | 90% | 🔼🔼🔼 Critical |
| E2E Scenarios | 60% | 85% | 🔼🔼 High |
| **Overall** | **89%** | **92%** | - |

### Priority Test Coverage Additions

#### P0 (Critical - Complete in Phase 1-2)
1. **Alembic Migration Tests** - Fresh database migration, upgrade/downgrade cycles, conflict detection
2. **DatabaseManager Tests** - Connector initialization, fallback, connection pooling, error handling

#### P1 (High - Complete in Phase 2-3)
3. **Telemetry API Tests** - All endpoint response formats, error cases, pagination, filtering
4. **Integration Test Fixtures** - Consistent database initialization, reusable test data builders

#### P2 (Medium - Complete in Phase 3-4)
5. **E2E Pipeline Tests** - Full pipeline flows with Cloud SQL schema
6. **Performance Tests** - Bulk insert, query optimization, connection pool sizing

---

## Success Criteria

### Phase 1 Complete (Week 1)
- [ ] All import errors resolved (33 errors → 0)
- [ ] Test dependencies documented and installed
- [ ] DatabaseManager test fixture created
- [ ] Environment variables standardized

### Phase 2 Complete (Week 2)
- [ ] Alembic migrations run cleanly (11 failures → 0)
- [ ] No duplicate table creation errors
- [ ] Migration test suite passes 100%

### Phase 3 Complete (Week 3)
- [ ] All integration tests pass (12 failures → 0)
- [ ] URL format issues resolved
- [ ] Mock patterns standardized

### Phase 4 Complete (Week 4)
- [ ] Telemetry tests aligned with schema (5 failures → 0)
- [ ] Test data fixtures comprehensive
- [ ] Field name mismatches resolved

### Final Success
- [ ] **0 test failures, 0 test errors**
- [ ] Test coverage ≥92%
- [ ] All CI/CD pipelines green
- [ ] Testing documentation complete

---

## Implementation Checklist

### Week 1: Foundation
- [ ] Install Cloud SQL connector in dev environment
- [ ] Create test database fixture library
- [ ] Fix Alembic migration file conflicts
- [ ] Update environment variable handling
- [ ] **Target: <50 failures**

### Week 2: Integration Layer
- [ ] Update all DatabaseManager test usage
- [ ] Fix URL format issues in TelemetryStore
- [ ] Replace MAIN_DB_PATH patches
- [ ] Standardize mock patterns
- [ ] **Target: <20 failures**

### Week 3: Data Layer
- [ ] Create comprehensive test data fixtures
- [ ] Update telemetry test expectations
- [ ] Fix field name mismatches
- [ ] Add missing parameters to tracking calls
- [ ] **Target: <10 failures**

### Week 4: E2E and Documentation
- [ ] Implement E2E test harness
- [ ] Migrate existing E2E tests
- [ ] Add new Cloud SQL E2E scenarios
- [ ] Document testing practices
- [ ] Update CI/CD configuration
- [ ] **Target: 0 failures**

---

## Related Issues

- Issue #44: API Backend Cloud SQL Migration (completed)
- Issue #45: Endpoint Migration PR (merged)
- Issue #32: Telemetry System Rollout (completed)
- Issue #40: Database Schema Migration (completed)

## References

- [Test Coverage Roadmap](docs/coverage-roadmap.md)
- [GCP Kubernetes Roadmap](docs/GCP_KUBERNETES_ROADMAP.md)
- [Telemetry Implementation Summary](docs/reference/TELEMETRY_IMPLEMENTATION_SUMMARY.md)
- [Full Issue Details](ISSUE_TEST_INFRASTRUCTURE_FIXES.md)

## Timeline

- **Start Date**: 2025-01-26
- **Phase 1-2 Complete**: 2025-02-09 (2 weeks)
- **Phase 3-4 Complete**: 2025-02-23 (4 weeks)
- **Phase 5-6 Complete**: 2025-03-09 (6 weeks)
- **Target Completion**: 2025-03-09

## Priority

**🔴 High Priority** - These test failures are blocking:
- Confident deployment to production
- Database migration validation
- CI/CD pipeline reliability
- Developer workflow efficiency

While the core functionality works (863/966 tests pass), the failing tests indicate technical debt that needs addressing before the Cloud SQL migration can be considered fully complete.

## Estimated Effort

**3-6 weeks** depending on team allocation:
- **Phase 1-2** (Critical): 1-2 weeks
- **Phase 3-4** (Important): 1-2 weeks
- **Phase 5-6** (Nice-to-have): 1-2 weeks
