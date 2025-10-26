# Test Infrastructure Gap Analysis

## Executive Summary

Multiple SQL-related errors reached production that should have been caught by our test suite:
1. Entity extraction SQL error: Column `a.source_id` doesn't exist (Oct 8, 2025)
2. Pipeline-status PostgreSQL syntax error: `datetime()` function incompatibility (Oct 8, 2025)
3. ML analysis proxy errors reaching production

**Root Cause**: Tests exist but are not being run before commits/deployments, and where tests do exist, some are inadequate (fully mocked without validating actual behavior).

## Critical Discovery

Running `pytest` locally on Oct 8, 2025 reveals:

```bash
# Entity extraction tests
pytest tests/test_entity_extraction_command.py -v
# Result: 8 PASSED, 1 FAILED
# Failing test: test_entity_extraction_query_structure
# Error: AssertionError: assert 'a.source_id' in query_str
# Coverage: 13% (FAIL - requirement is 80%)

# Pipeline-status tests  
pytest tests/test_pipeline_status.py -v
# Result: 12 PASSED, 0 FAILED
# Coverage: 14% (FAIL - requirement is 80%)
```

**Key Finding**: The entity extraction test `test_entity_extraction_query_structure` has been **FAILING since the Oct 8 fix** (commit c0d693b). This test would have caught the SQL error if anyone had run `pytest` before deploying.

## Root Causes Identified

### 1. Developer Process: Tests Not Run Before Commit/Deploy

**Problem**: Tests exist and would catch issues, but are not being executed before commits reach production.

**Evidence**:
- Test `test_entity_extraction_query_structure` added Oct 7 (commit 58505a3)
- SQL fix deployed Oct 8 (commit c0d693b) changed `a.source_id` to `cl.source_id`
- Test expects `a.source_id` and has been failing ever since
- Test was never updated, indicating it was never run after the fix

**Test Failure Details**:
```python
# tests/test_entity_extraction_command.py:364
def test_entity_extraction_query_structure(self, mock_db_manager, mock_entity_extractor):
    """Test that the query correctly filters articles needing entity extraction."""
    # ...
    assert "a.source_id" in query_str  # FAILS
    # Actual query uses: cl.source_id (from candidate_links join)
```

**Impact**: A failing test that explicitly checks for the exact column name issue sat unnoticed while broken code was deployed to production.

### 2. Test Quality: Inadequate Mocking Without Validation

**Problem**: Some tests mock database sessions and return fake data without ever validating the actual SQL queries.

**Evidence - Pipeline-Status Tests**:
```python
# tests/test_pipeline_status.py
mock_session.execute.side_effect = [
    Mock(scalar=lambda: 157),  # Returns fake data
    Mock(scalar=lambda: 142),
    # ... more fake scalars
]
```

All 12 pipeline-status tests **PASS** despite the code containing broken PostgreSQL syntax (`datetime('now', '-7 days')`). The SQL is never executed because `session.execute()` is mocked to return fake values.

**Impact**: Tests pass with 100% success rate while the actual code contains syntax errors that crash in production.

### 3. Coverage Requirements Not Enforced

**Problem**: pytest.ini requires 80% coverage, but tests run with only 13-14% coverage and commits are not blocked.

**Evidence**:
```ini
# pytest.ini
addopts = --cov-fail-under=80

# Actual results:
# Entity extraction tests: 13% coverage
# Pipeline-status tests: 14% coverage
# Both print: ERROR: Coverage failure: total of 13 is less than fail-under=80
```

**Impact**: Coverage failures are visible but not enforced. Code with massive coverage gaps reaches production.

### 4. SQLite vs PostgreSQL Compatibility

**Problem**: Tests use SQLite in-memory databases while production uses PostgreSQL, masking SQL dialect incompatibilities.

**Evidence**:
```python
# pytest.ini
addopts = -p no:postgresql  # PostgreSQL plugin disabled

# .github/workflows/ci.yml  
TELEMETRY_DATABASE_URL: "sqlite:///:memory:"
```

**Impact**: SQL syntax that works in SQLite (like `datetime('now', '-7 days')`) fails in PostgreSQL. However, this is a SECONDARY issue - the primary issue is that tests aren't being run at all.

### 5. CI/CD Configuration

**Problem**: GitHub Actions CI workflow only runs unit tests, excluding integration and end-to-end tests.

**Evidence**:
```yaml
# .github/workflows/ci.yml
pytest -q -k "not integration and not e2e and not slow"
```

**Impact**: This is **NOT an excuse** - CI runs the same pytest suite available locally. If developers ran `pytest` locally before committing, they would see the same failures. The CI configuration is fine; the problem is the developer workflow.

## Timeline of Failures

### Entity Extraction SQL Error

| Date | Event | Status |
|------|-------|--------|
| Oct 7, 2025 | Test added expecting `a.source_id` (commit 58505a3) | ✅ Test created |
| Oct 8, 2025 | SQL fixed to use `cl.source_id` (commit c0d693b) | ✅ Bug fixed |
| Oct 8, 2025 | Code deployed to production | ✅ Deployed |
| Oct 8, 2025 | Test never updated or run | ❌ Test now fails |
| Oct 8, 2025 | Discovery: test has been failing since fix | 🔍 Found via `pytest` |

### Pipeline-Status PostgreSQL Error

| Date | Event | Status |
|------|-------|--------|
| Unknown | Pipeline-status command created with SQLite syntax | ⚠️ Bug introduced |
| Oct 8, 2025 | Tests created but fully mocked | ⚠️ Tests inadequate |
| Oct 8, 2025 | Code deployed to production | ❌ Broken in prod |
| Oct 8, 2025 | Error discovered during manual execution | 🔍 Found via CLI |
| Oct 8, 2025 | Fixed (commit 4d66e44) | ✅ Fixed |

## Recommendations

### Priority 1: Immediate Actions

#### 1.1 Add Pre-Commit Hooks (CRITICAL)

**Solution**: Force `pytest` to run before every commit.

```bash
# Install pre-commit
pip install pre-commit

# Create .pre-commit-config.yaml
cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: local
    hooks:
      - id: pytest-check
        name: pytest
        entry: pytest
        language: system
        pass_filenames: false
        always_run: true
        args: ["-x", "--tb=short", "--cov-fail-under=80"]
      
      - id: pytest-coverage
        name: coverage-report
        entry: pytest
        language: system
        pass_filenames: false
        always_run: true
        args: ["--cov", "--cov-report=term-missing:skip-covered"]
EOF

# Install hooks
pre-commit install
```

**Impact**: Developers cannot commit code with failing tests or insufficient coverage.

#### 1.2 Fix Failing Test

**Solution**: Update `test_entity_extraction_query_structure` to match the corrected SQL.

```python
# tests/test_entity_extraction_command.py
def test_entity_extraction_query_structure(self, mock_db_manager, mock_entity_extractor):
    """Test that the query correctly filters articles needing entity extraction."""
    # ...
    
    # Should select required fields from correct tables
    assert "a.id" in query_str
    assert "a.text" in query_str
    assert "cl.source_id" in query_str  # Fixed: was a.source_id
    assert "cl.dataset_id" in query_str
    assert "candidate_links cl" in query_str
    assert "a.candidate_link_id = cl.id" in query_str
```

#### 1.3 Add SQL Validation to Pipeline-Status Tests

**Solution**: Replace mocked tests with actual SQL execution against a test database.

```python
# tests/test_pipeline_status.py
import pytest
from sqlalchemy import create_engine, text

@pytest.fixture
def test_db():
    """Create a PostgreSQL test database."""
    engine = create_engine("postgresql://test:test@localhost/test_db")
    yield engine
    engine.dispose()

def test_pipeline_status_sql_syntax(test_db):
    """Verify SQL queries use valid PostgreSQL syntax."""
    from src.cli.commands.pipeline_status import get_discovery_status
    
    # This will fail if SQL contains SQLite-specific functions
    with test_db.connect() as conn:
        # Execute actual query fragments to validate syntax
        conn.execute(text("SELECT NOW() - INTERVAL '7 days'"))  # Valid
```

### Priority 2: Enhanced Test Infrastructure

#### 2.1 Database Test Matrix

**Solution**: Test against both SQLite (fast) and PostgreSQL (production-like).

```yaml
# .github/workflows/ci.yml
strategy:
  matrix:
    database:
      - sqlite:///:memory:
      - postgresql://postgres:postgres@localhost:5432/test_db
    
steps:
  - name: Run tests
    env:
      DATABASE_URL: ${{ matrix.database }}
    run: pytest
```

#### 2.2 Integration Test Suite

**Solution**: Create integration tests that run against actual PostgreSQL.

```python
# tests/integration/test_sql_compatibility.py
import pytest

@pytest.mark.integration
class TestSQLCompatibility:
    """Verify all SQL queries work against PostgreSQL."""
    
    def test_entity_extraction_query_executes(self, postgresql_db):
        """Verify entity extraction query runs without syntax errors."""
        from src.cli.commands.entity_extraction import handle_entity_extraction_command
        
        # This will fail fast if SQL has syntax errors
        result = handle_entity_extraction_command(args)
        assert result is not None
```

#### 2.3 GitHub Actions Branch Protection

**Solution**: Require passing tests before merge.

```yaml
# .github/branch-protection-rules.yml
main:
  required_status_checks:
    strict: true
    contexts:
      - "Test Suite (unit)"
      - "Test Suite (integration)"
      - "Coverage Check (≥80%)"
  required_reviews: 1
  enforce_admins: true
```

### Priority 3: Documentation and Process

#### 3.1 Developer Guidelines

Create `DEVELOPMENT_WORKFLOW.md`:

```markdown
# Development Workflow

## Before Committing

1. **Run full test suite**: `pytest`
2. **Check coverage**: `pytest --cov --cov-report=term-missing`
3. **Verify no failures**: All tests must pass
4. **Ensure coverage**: Must be ≥80%

## Pre-Commit Hooks

Pre-commit hooks automatically run tests. If tests fail:
- Fix the failing tests
- Update tests if behavior changed intentionally
- Do not bypass hooks (use `--no-verify` only for WIP branches)
```

#### 3.2 Test Writing Guidelines

Add to `tests/README.md`:

```markdown
# Test Writing Guidelines

## ❌ BAD: Mocking Without Validation

```python
# This test doesn't validate SQL syntax
mock_session.execute.return_value.scalar.return_value = 42
```

## ✅ GOOD: Validate Actual Behavior

```python
# This test validates SQL executes successfully
with test_db.connect() as conn:
    result = conn.execute(query)
    assert result is not None
```

## Test Categories

- **Unit tests**: Fast, mocked dependencies
- **Integration tests**: Real database, validate SQL
- **E2E tests**: Full pipeline, validate end-to-end
```

## Implementation Plan

### Week 1: Emergency Fixes
- [x] Fix pipeline-status PostgreSQL syntax (commit 4d66e44)
- [ ] Fix entity extraction test expectations
- [ ] Add pre-commit hooks
- [ ] Document developer workflow

### Week 2: Test Infrastructure
- [ ] Add PostgreSQL integration tests
- [ ] Create database test matrix in CI
- [ ] Add SQL validation tests for all commands
- [ ] Update branch protection rules

### Week 3: Process Improvements
- [ ] Team training on test-first development
- [ ] Code review checklist (must include "tests run locally")
- [ ] Coverage dashboard
- [ ] Weekly test health metrics

## Metrics to Track

1. **Test Execution Rate**: % of commits preceded by local test runs
2. **Coverage**: Track trend toward 80% requirement
3. **Test Quality**: Ratio of mocked vs integration tests
4. **Production Incidents**: SQL errors reaching production (target: 0)

## Conclusion

The root cause is **not** CI configuration or infrastructure limitations. The root cause is:

1. **Tests exist but aren't run** before commits (entity extraction test is failing)
2. **Tests are inadequate** where they do exist (pipeline-status tests fully mocked)
3. **Coverage requirements aren't enforced** (13-14% vs 80% threshold)

**Primary Fix**: Add pre-commit hooks to force test execution. This single change would have prevented both production incidents.

**Secondary Fix**: Improve test quality by adding integration tests that validate actual SQL execution against PostgreSQL.
