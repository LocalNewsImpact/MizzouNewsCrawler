# Test Infrastructure Fixes Required for Cloud SQL Migration

## Issue Summary

After the Cloud SQL migration, approximately **103 out of 966 tests** are failing or erroring (10.7%). The test suite needs systematic updates to align with the new Cloud SQL infrastructure, fix Alembic migration conflicts, and update test expectations for the modernized telemetry system.

**Test Results:**
- ✅ **863 passed** (89.3%)
- ❌ **61 failed** (6.3%)
- ⚠️ **33 errors** (3.4%)
- ⏭️ **9 skipped** (0.9%)
- **Total**: 966 tests

## Problem Categories

### 1. Cloud SQL Connector Missing (33 errors)

**Issue:** Tests fail with `ModuleNotFoundError: No module named 'google.cloud.sql.connector'`

**Root Cause:** The `DatabaseManager` class attempts to use Cloud SQL connector when `USE_CLOUD_SQL_CONNECTOR` is set, but the connector is not available in the test environment.

**Affected Areas:**
- E2E tests (`tests/e2e/`)
- Integration tests (`tests/*/test_*_integration.py`)
- Reporting tests (`tests/reporting/`)
- CLI command tests requiring database access

**Example Error:**
```python
# From src/models/database.py line 97
def _create_cloud_sql_engine(self):
    """Create database engine using Cloud SQL Python Connector."""
    from src.config import CLOUD_SQL_INSTANCE  # <- Fails if module not installed
```

**Affected Test Files (Sample):**
- `tests/e2e/test_extraction_analysis_pipeline.py`
- `tests/e2e/test_county_pipeline_golden_path.py`
- `tests/e2e/test_telemetry_dashboard_golden_path.py`
- `tests/reporting/test_publisher_stats.py`
- `tests/reporting/test_telemetry_summary.py`

### 2. Alembic Migration Conflicts (11 failures)

**Issue:** Multiple migrations try to create the same `byline_cleaning_telemetry` table, causing "table already exists" errors.

**Root Cause:** Two separate migrations both create the `byline_cleaning_telemetry` table:
1. `e3114395bcc4_add_api_backend_and_telemetry_tables.py` (earlier migration)
2. `a9957c3054a4_add_remaining_telemetry_tables.py` (later migration)

**Example Error:**
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) table byline_cleaning_telemetry already exists
```

**Affected Test Files:**
- `tests/alembic/test_alembic_migrations.py` - All 11 tests fail
  - `test_alembic_upgrade_head_sqlite`
  - `test_alembic_downgrade_one_revision`
  - `test_alembic_upgrade_head_postgres` (if PostgreSQL available)
  - `test_alembic_migration_history_valid`
  - `test_alembic_no_orphan_migrations`
  - `test_alembic_revision_descriptions_exist`
  - `test_alembic_can_generate_new_migration`
  - `test_alembic_migrations_are_reversible`
  - `test_alembic_schema_matches_models`
  - `test_alembic_no_migration_conflicts`
  - `test_alembic_foreign_keys_valid`

**Migration File Locations:**
```
alembic/versions/e3114395bcc4_add_api_backend_and_telemetry_tables.py:
    op.create_table('byline_cleaning_telemetry', ...)  # First creation

alembic/versions/a9957c3054a4_add_remaining_telemetry_tables.py:
    op.create_table('byline_cleaning_telemetry', ...)  # Duplicate creation
```

### 3. Integration Tests Requiring Cloud SQL Connector (9 errors + 3 failures)

**Issue:** Integration tests that connect to real databases fail because they can't initialize `DatabaseManager`.

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

**Example Test Pattern:**
```python
def test_get_sources_integration_sqlite(tmp_path):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    
    # This fails because DatabaseManager tries Cloud SQL first
    dbm = DatabaseManager(database_url=db_url)  # <- Error here
```

### 4. Telemetry Tests with Outdated Expectations (5 failures)

**Issue:** Tests expect old CSV-based data or outdated API response formats after migration to Cloud SQL.

**Root Cause:** Tests were written for the old CSV-based system and haven't been updated for:
- New database schema
- Updated telemetry table structures
- Changed API endpoint response formats
- New field names (e.g., `reviewed_by` → `reviewer`)

**Affected Test Files:**
- `tests/test_telemetry_api.py`
  - `test_telemetry_summary_endpoint` - Expected 5 extractions, got 106
  - `test_http_errors_endpoint` - Expected ≥2 errors, got 1
  - `test_publisher_stats_endpoint` - Can't find "good-site.com" in test data
- `tests/test_telemetry_http_status.py`
  - `test_track_http_status_inserts_row` - Missing `status_category` parameter
- `tests/utils/test_operation_tracker.py` (4 failures)
  - Tests passing raw file paths instead of `sqlite:///` URLs
  - URL parsing failures in `TelemetryStore` initialization

**Example Issues:**

**a) Test Data Mismatch:**
```python
# Test expects 5 test records, but gets 106 from actual database
def test_telemetry_summary_endpoint(test_db_session):
    response = client.get("/api/telemetry/summary")
    data = response.json()
    assert len(data["extractions"]) == 5  # Fails: actual is 106
```

**b) Missing Field:**
```python
# Missing status_category parameter in track_http_status call
tracker.track_http_status(
    operation_id="op-1",
    source_id="src-1",
    # ... other params
    # Missing: status_category="4xx"  <- Should be derived from status_code
)
```

**c) URL Format Issue:**
```python
# TelemetryStore expects sqlite:/// URL format
db_path = tmp_path / "tracker.db"
store = TelemetryStore(database=str(db_path))  # Should be f"sqlite:///{db_path}"
```

### 5. Missing MAIN_DB_PATH Constant (9 errors + 3 failures)

**Issue:** Tests try to patch `backend.app.main.MAIN_DB_PATH` which was removed during Cloud SQL migration.

**Root Cause:** The backend migrated from using a hardcoded `MAIN_DB_PATH` constant to using `DatabaseManager`. Tests still reference the old constant.

**Affected Test Files:**
- `tests/test_dashboard_failures.py`
- `tests/test_telemetry_deployment_readiness.py`
- Several backend API tests

**Example:**
```python
# Old test code
@patch("backend.app.main.MAIN_DB_PATH", new_callable=lambda: tmp_path / "test.db")
def test_something(tmp_path):
    # This patch fails because MAIN_DB_PATH no longer exists
    pass

# Should be updated to:
@patch("backend.app.main.db_manager")
def test_something(mock_db_manager):
    pass
```

---

## Roadmap to Fixing

### Phase 1: Environment and Dependencies (Week 1)

**Goal:** Ensure test environment can run all tests without import errors.

#### Task 1.1: Add Cloud SQL Connector to Test Dependencies
- [ ] Add `google-cloud-sql-python-connector` to `requirements-dev.txt`
- [ ] Add conditional import handling in test fixtures
- [ ] Create mock Cloud SQL connector for tests that don't need real connections

**Files to Update:**
```python
# requirements-dev.txt
google-cloud-sql-python-connector>=1.2.0  # For testing Cloud SQL connectivity

# tests/conftest.py - Add mock Cloud SQL connector
@pytest.fixture
def mock_cloud_sql_connector(monkeypatch):
    """Mock Cloud SQL connector for tests."""
    monkeypatch.setenv("USE_CLOUD_SQL_CONNECTOR", "false")
    yield
```

#### Task 1.2: Update DatabaseManager Test Initialization
- [ ] Create `DatabaseManager` test fixture that forces SQLite mode
- [ ] Add environment variable override in test setup
- [ ] Update all integration tests to use the fixture

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

### Phase 2: Fix Alembic Migration Conflicts (Week 1-2)

**Goal:** Resolve duplicate table creation in migrations.

#### Task 2.1: Audit Migration Files
- [ ] List all tables created by each migration
- [ ] Identify duplicate table creations
- [ ] Document migration dependencies

**Script:**
```bash
# Check for duplicate table creations
cd alembic/versions
for table in $(grep -h "op.create_table" *.py | sed "s/.*create_table('\([^']*\)'.*/\1/" | sort | uniq -d); do
    echo "Duplicate table: $table"
    grep -l "create_table('$table'" *.py
done
```

#### Task 2.2: Consolidate Migrations
- [ ] Option A: Remove duplicate table creation from later migration
- [ ] Option B: Add conditional creation (IF NOT EXISTS logic)
- [ ] Option C: Create new migration to reconcile conflicts

**Recommended: Option A - Clean up later migration**

```python
# In a9957c3054a4_add_remaining_telemetry_tables.py

def upgrade():
    # Remove byline_cleaning_telemetry creation - already in e3114395bcc4
    # Keep only new tables not created by previous migrations
    
    # Add byline_cleaning_telemetry_reviews (this is unique to this migration)
    op.create_table(
        'byline_cleaning_telemetry_reviews',
        # ... columns
    )
    
    # Remove duplicate byline_cleaning_telemetry table creation
```

#### Task 2.3: Test Migration Path
- [ ] Test fresh database: `alembic upgrade head`
- [ ] Test downgrade: `alembic downgrade -1`
- [ ] Test upgrade again: `alembic upgrade head`
- [ ] Verify no duplicate table errors

### Phase 3: Fix Integration Tests (Week 2)

**Goal:** All integration tests pass with SQLite backend.

#### Task 3.1: Update Test Database Initialization
- [ ] Replace direct `DatabaseManager()` calls with test fixture
- [ ] Ensure all tests use `monkeypatch` to disable Cloud SQL
- [ ] Standardize URL format: always use `sqlite:///path`

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

#### Task 3.2: Fix URL Format Issues
- [ ] Update all `TelemetryStore` initializations to use proper URLs
- [ ] Add URL validation in test fixtures
- [ ] Create helper function for test database URLs

```python
# tests/helpers/database.py
def make_test_db_url(tmp_path, name="test.db"):
    """Create properly formatted SQLite URL for testing."""
    db_path = tmp_path / name
    return f"sqlite:///{db_path}"
```

#### Task 3.3: Update Mock Patterns
- [ ] Replace `@patch("backend.app.main.MAIN_DB_PATH")` with `@patch("backend.app.main.db_manager")`
- [ ] Create reusable mock database manager fixture
- [ ] Update all affected test files

**Example:**
```python
# tests/conftest.py
@pytest.fixture
def mock_db_manager(tmp_path):
    """Mock DatabaseManager for API tests."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    with patch("backend.app.main.db_manager") as mock:
        mock.database_url = db_url
        mock.engine = create_engine(db_url)
        mock.get_session.return_value = sessionmaker(bind=mock.engine)()
        yield mock
```

### Phase 4: Fix Telemetry Test Expectations (Week 2-3)

**Goal:** Align test expectations with Cloud SQL schema and data.

#### Task 4.1: Update Test Data Fixtures
- [ ] Create comprehensive test data that matches production schema
- [ ] Use SQLAlchemy models to insert test data (not raw SQL)
- [ ] Document expected data counts and relationships

```python
# tests/fixtures/telemetry_data.py
@pytest.fixture
def sample_extractions(test_database_manager):
    """Create sample extraction telemetry records."""
    from src.models.telemetry import ExtractionTelemetryV2
    
    session = test_database_manager.session
    
    # Create exactly 5 test records for predictable assertions
    for i in range(5):
        record = ExtractionTelemetryV2(
            operation_id=f"op-{i}",
            article_id=f"art-{i}",
            url=f"https://test-site.com/article-{i}",
            publisher="test-site.com",
            host="test-site.com",
            http_status_code=200,
            successful_method="newspaper4k",
            extraction_timestamp=datetime.utcnow()
        )
        session.add(record)
    
    session.commit()
    return session
```

#### Task 4.2: Update API Response Assertions
- [ ] Document actual API response formats
- [ ] Update test assertions to match reality
- [ ] Add response schema validation

```python
# Before
def test_telemetry_summary_endpoint():
    response = client.get("/api/telemetry/summary")
    data = response.json()
    assert len(data["extractions"]) == 5  # Hardcoded expectation

# After
def test_telemetry_summary_endpoint(sample_extractions):
    response = client.get("/api/telemetry/summary")
    data = response.json()
    
    # Assert structure
    assert "extractions" in data
    assert isinstance(data["extractions"], list)
    
    # Assert based on fixture data
    assert len(data["extractions"]) == 5
    
    # Validate schema
    for extraction in data["extractions"]:
        assert "operation_id" in extraction
        assert "article_id" in extraction
        assert "http_status_code" in extraction
```

#### Task 4.3: Fix Field Name Mismatches
- [ ] Audit all field name changes (e.g., `reviewed_by` → `reviewer`)
- [ ] Update test code to use new field names
- [ ] Add field name constants to avoid hardcoded strings

```python
# src/models/constants.py
class TelemetryFields:
    """Standard field names for telemetry data."""
    REVIEWER = "reviewer"  # Not "reviewed_by"
    ARTICLE_ID = "article_id"
    OPERATION_ID = "operation_id"
    # ... etc

# In tests
assert record[TelemetryFields.REVIEWER] == "test-reviewer"
```

#### Task 4.4: Add Missing Parameters
- [ ] Audit all telemetry tracking calls
- [ ] Add missing parameters (e.g., `status_category`)
- [ ] Make parameters optional with sensible defaults

```python
# In src/utils/telemetry.py
def track_http_status(
    self,
    operation_id: str,
    source_id: str,
    source_url: str,
    discovery_method: DiscoveryMethod,
    attempted_url: str,
    status_code: int,
    response_time_ms: float,
    error_message: str | None = None,
    content_length: int = 0,
    status_category: str | None = None,  # Add parameter
):
    """Track HTTP status with all required fields."""
    # Auto-derive status_category if not provided
    if status_category is None:
        if 200 <= status_code < 300:
            status_category = "2xx"
        elif 300 <= status_code < 400:
            status_category = "3xx"
        elif 400 <= status_code < 500:
            status_category = "4xx"
        elif 500 <= status_code < 600:
            status_category = "5xx"
        else:
            status_category = "other"
    
    # ... rest of implementation
```

### Phase 5: Create E2E Test Suite (Week 3-4)

**Goal:** Comprehensive end-to-end tests that work with Cloud SQL schema.

#### Task 5.1: Design E2E Test Strategy
- [ ] Define test scenarios covering full pipeline
- [ ] Design test data that exercises all code paths
- [ ] Document expected outcomes

**Test Scenarios:**
1. **Discovery → Extraction → Analysis → Telemetry**
   - Input: Source with RSS feed
   - Expected: Articles extracted, entities identified, telemetry recorded
   
2. **Failed Extraction Recovery**
   - Input: Article with extraction failure
   - Expected: Failure recorded, retry scheduled, telemetry updated
   
3. **Duplicate Detection**
   - Input: Multiple articles with similar content
   - Expected: Duplicates flagged, telemetry shows near-misses

#### Task 5.2: Create Shared E2E Fixtures
- [ ] Reusable test data builders
- [ ] Mock external services (RSS feeds, web pages)
- [ ] Deterministic test databases

```python
# tests/e2e/conftest.py
@pytest.fixture
def e2e_test_database(tmp_path):
    """Create isolated E2E test database with schema."""
    db_url = f"sqlite:///{tmp_path / 'e2e_test.db'}"
    
    with patch.dict(os.environ, {
        "USE_CLOUD_SQL_CONNECTOR": "false",
        "DATABASE_URL": db_url
    }):
        dbm = DatabaseManager(database_url=db_url)
        
        # Seed with minimal test data
        seed_test_data(dbm)
        
        yield dbm
        
        dbm.close()

def seed_test_data(dbm):
    """Seed database with deterministic test data."""
    # Add sources
    # Add articles
    # Add candidate links
    # etc.
```

#### Task 5.3: Implement E2E Tests
- [ ] Migrate existing E2E tests to use new fixtures
- [ ] Add new E2E tests for Cloud SQL features
- [ ] Verify tests pass in CI/CD

### Phase 6: Documentation and CI/CD (Week 4)

**Goal:** Document testing approach and integrate into CI/CD.

#### Task 6.1: Create Testing Documentation
- [ ] Document test infrastructure changes
- [ ] Create testing best practices guide
- [ ] Document how to run tests locally

**Documentation Outline:**
```markdown
# Testing Guide

## Running Tests Locally

### Setup
```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Set environment for local testing
export USE_CLOUD_SQL_CONNECTOR=false
export DATABASE_URL=sqlite:///data/test.db
```

### Run All Tests
```bash
pytest -v
```

### Run Specific Test Categories
```bash
pytest -v -m integration  # Integration tests
pytest -v -m e2e          # E2E tests
pytest tests/alembic/     # Alembic tests
```

## Test Database Setup

Tests use SQLite by default. To test against PostgreSQL:

```bash
# Start PostgreSQL with Docker
docker run -p 5432:5432 -e POSTGRES_PASSWORD=test postgres:15

# Run tests against PostgreSQL
export DATABASE_URL=postgresql://postgres:test@localhost:5432/test_db
pytest -v
```
```

#### Task 6.2: Update CI/CD Pipeline
- [ ] Add test database setup to CI
- [ ] Configure environment variables for tests
- [ ] Add test result reporting

```yaml
# .github/workflows/test.yml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      
      - name: Run tests
        env:
          USE_CLOUD_SQL_CONNECTOR: false
          DATABASE_URL: sqlite:///test.db
        run: |
          pytest -v --cov=src --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

#### Task 6.3: Add Test Quality Checks
- [ ] Set minimum coverage threshold
- [ ] Add test performance monitoring
- [ ] Create test reliability dashboard

---

## Test Coverage Plan

### Current Coverage Analysis

**Well-Tested Areas (>90% coverage):**
- ✅ Core discovery logic (`src/crawler/discovery.py`)
- ✅ Content extraction (`src/crawler/extractor.py`)
- ✅ Entity extraction (`src/utils/entity_extraction.py`)
- ✅ Telemetry store (`src/telemetry/store.py`)
- ✅ Configuration management (`src/config.py`)

**Under-Tested Areas (<70% coverage):**
- ⚠️ Database migrations (`alembic/versions/`) - Currently 0% due to conflicts
- ⚠️ Cloud SQL connector integration - Missing tests
- ⚠️ API endpoint error handling - Needs more edge case coverage
- ⚠️ Telemetry aggregation queries - Complex SQL needs validation

**Missing Coverage:**
- ❌ Cloud SQL Python Connector initialization
- ❌ Connection pool management
- ❌ Database failover scenarios
- ❌ Large dataset performance tests

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

### Test Types Distribution

**Current:**
- Unit tests: ~700 tests (72%)
- Integration tests: ~200 tests (21%)
- E2E tests: ~50 tests (5%)
- Performance tests: ~16 tests (2%)

**Target:**
- Unit tests: ~800 tests (70%)
- Integration tests: ~250 tests (22%)
- E2E tests: ~75 tests (7%)
- Performance tests: ~25 tests (2%)

### Priority Test Coverage Additions

#### P0 (Critical - Complete in Phase 1-2)
1. **Alembic Migration Tests** (Currently broken)
   - Fresh database migration
   - Upgrade/downgrade cycles
   - Migration conflict detection
   - Schema validation

2. **DatabaseManager Tests** (Cloud SQL integration)
   - Connector initialization
   - Fallback to direct connection
   - Connection pooling
   - Error handling

#### P1 (High - Complete in Phase 2-3)
3. **Telemetry API Tests** (Update expectations)
   - All endpoint response formats
   - Error cases
   - Pagination
   - Filtering/sorting

4. **Integration Test Fixtures** (Standardize)
   - Consistent database initialization
   - Reusable test data builders
   - Mock external services

#### P2 (Medium - Complete in Phase 3-4)
5. **E2E Pipeline Tests** (Cloud SQL schema)
   - Discovery → Extraction → Analysis
   - Failure recovery flows
   - Duplicate detection
   - County report generation

6. **Performance Tests** (Cloud SQL)
   - Bulk insert performance
   - Query optimization
   - Connection pool sizing
   - Large dataset handling

#### P3 (Nice to have - Complete in Phase 4+)
7. **Load Tests**
   - Concurrent API requests
   - High-volume data ingestion
   - Database under stress

8. **Chaos Tests**
   - Database connection failures
   - Network timeouts
   - Partial data scenarios

### Test Infrastructure Improvements

#### Immediate (Phase 1)
- [ ] Add Cloud SQL connector to dev dependencies
- [ ] Create standard test database fixtures
- [ ] Fix Alembic migration conflicts
- [ ] Update environment variable handling in tests

#### Short-term (Phase 2-3)
- [ ] Implement shared E2E test harness
- [ ] Add test data builders/factories
- [ ] Create API test client fixture
- [ ] Add database snapshot/restore utilities

#### Long-term (Phase 4+)
- [ ] Containerized test databases (Docker)
- [ ] Test data generation tools
- [ ] Visual regression testing for dashboards
- [ ] Performance benchmarking suite
- [ ] Mutation testing for critical paths

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
- [ ] Migration documentation updated

### Phase 3 Complete (Week 3)
- [ ] All integration tests pass (12 failures → 0)
- [ ] URL format issues resolved
- [ ] Mock patterns standardized
- [ ] Integration test documentation complete

### Phase 4 Complete (Week 4)
- [ ] Telemetry tests aligned with schema (5 failures → 0)
- [ ] Test data fixtures comprehensive
- [ ] API response validation complete
- [ ] Field name mismatches resolved

### Final Success (End of Phase 6)
- [ ] **0 test failures, 0 test errors**
- [ ] Test coverage ≥92%
- [ ] All CI/CD pipelines green
- [ ] Testing documentation complete
- [ ] Developer onboarding guide published

---

## Implementation Checklist

### Week 1: Foundation
- [ ] Install Cloud SQL connector in dev environment
- [ ] Create test database fixture library
- [ ] Fix Alembic migration file conflicts
- [ ] Update environment variable handling
- [ ] Run full test suite - target: <50 failures

### Week 2: Integration Layer
- [ ] Update all DatabaseManager test usage
- [ ] Fix URL format issues in TelemetryStore
- [ ] Replace MAIN_DB_PATH patches
- [ ] Standardize mock patterns
- [ ] Run full test suite - target: <20 failures

### Week 3: Data Layer
- [ ] Create comprehensive test data fixtures
- [ ] Update telemetry test expectations
- [ ] Fix field name mismatches
- [ ] Add missing parameters to tracking calls
- [ ] Run full test suite - target: <10 failures

### Week 4: E2E and Documentation
- [ ] Implement E2E test harness
- [ ] Migrate existing E2E tests
- [ ] Add new Cloud SQL E2E scenarios
- [ ] Document testing practices
- [ ] Update CI/CD configuration
- [ ] Run full test suite - target: 0 failures

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
- [Cloud SQL Migration Status](CLOUD_SQL_MIGRATION_COMPLETION_SUMMARY.md)
- [Test Status Report](TEST_STATUS_REPORT.md)

---

## Assignees

- **Phase 1-2**: DevOps/Infrastructure team
- **Phase 3-4**: Backend development team  
- **Phase 5-6**: QA/Testing team + Documentation team

## Timeline

- **Start Date**: 2025-01-26
- **Phase 1 Complete**: 2025-02-02 (1 week)
- **Phase 2 Complete**: 2025-02-09 (2 weeks)
- **Phase 3 Complete**: 2025-02-16 (3 weeks)
- **Phase 4 Complete**: 2025-02-23 (4 weeks)
- **Phase 5 Complete**: 2025-03-02 (5 weeks)
- **Phase 6 Complete**: 2025-03-09 (6 weeks)
- **Target Completion**: 2025-03-09

## Priority

**High Priority** - These test failures are blocking:
- Confident deployment to production
- Database migration validation
- CI/CD pipeline reliability
- Developer workflow efficiency

While the core functionality works (863/966 tests pass), the failing tests indicate technical debt that needs addressing before the Cloud SQL migration can be considered fully complete.
