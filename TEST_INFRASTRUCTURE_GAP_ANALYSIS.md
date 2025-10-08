# Test Infrastructure Gap Analysis

## Executive Summary

Multiple critical SQL errors made it to production that should have been caught by automated testing:

1. **Entity extraction SQL error** (Issue #57): Referenced non-existent `a.source_id` column
2. **Pipeline-status PostgreSQL syntax error**: Used SQLite `datetime()` function instead of PostgreSQL `NOW() - INTERVAL`

## Root Cause Analysis

### 1. **Mock-Only Unit Tests Don't Validate SQL Syntax**

**Problem**: Unit tests mock the database session entirely, never executing actual SQL.

**Evidence** (`tests/test_entity_extraction_command.py`):
```python
def test_successful_entity_extraction(mock_db_manager, mock_entity_extractor, ...):
    # Mock returns fake data without running SQL
    mock_session.execute.return_value.fetchall.return_value = [
        (uuid.uuid4(), "Article text", "hash123", 1, 1)
    ]
```

**What This Misses**:
- SQL syntax errors (e.g., `datetime()` vs `NOW()`)
- Non-existent column references (e.g., `a.source_id`)
- Join errors
- Database-specific SQL differences (SQLite vs PostgreSQL)

### 2. **Integration Tests Are Excluded from CI**

**Problem**: CI explicitly excludes integration tests.

**Evidence** (`.github/workflows/ci.yml`):
```yaml
- name: Run unit tests (no coverage gating)
  env:
    TELEMETRY_DATABASE_URL: "sqlite:///:memory:"
  run: |
    # Run fast tests only; exclude integration/e2e/slow markers
    pytest -q -k "not integration and not e2e and not slow"
```

**What This Means**:
- Integration tests that would catch SQL errors are **never run in CI**
- Only mocked unit tests run, which don't validate SQL
- No PostgreSQL database is spun up for testing

### 3. **SQLite vs PostgreSQL Syntax Differences**

**Problem**: Development/tests use SQLite, production uses PostgreSQL with incompatible SQL syntax.

**Evidence**:
- Tests use: `TELEMETRY_DATABASE_URL: "sqlite:///:memory:"`
- Production uses: Cloud SQL (PostgreSQL)
- SQLite accepts: `datetime('now', '-7 days')`
- PostgreSQL requires: `NOW() - INTERVAL '7 days'`

**Critical Differences**:
| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Date math | `datetime('now', '-7 days')` | `NOW() - INTERVAL '7 days'` |
| String concat | `||` or `+` | `||` |
| Boolean type | 0/1 integers | TRUE/FALSE |
| JSON | Limited | Full JSONB support |
| Type checking | Loose | Strict |

### 4. **No SQL Linting or Static Analysis**

**Problem**: No automated SQL syntax validation.

**Evidence**:
- `ruff`, `black`, `isort` check Python code
- No `sqlfluff`, `sqlcheck`, or similar for SQL
- Raw SQL strings in code aren't validated
- SQLAlchemy text() queries bypass type checking

### 5. **PR CI Only Runs Against Main Branch**

**Problem**: CI doesn't run for feature branches.

**Evidence** (`.github/workflows/ci.yml`):
```yaml
on:
  push:
    branches: [ main ]  # Only main branch
  pull_request:
    branches: [ main ]  # Only PRs to main
```

**Impact**:
- Feature branch `feature/gcp-kubernetes-deployment` changes never tested in CI
- SQL errors only discovered after manual deployment
- No pre-merge validation

## Specific Failures

### Issue #57: Entity Extraction SQL Error

**File**: `src/cli/commands/entity_extraction.py`

**Bad SQL** (Commit before fix):
```sql
SELECT a.id, a.text, a.text_hash, a.source_id, a.dataset_id  -- ❌ These columns don't exist
FROM articles a
WHERE a.text IS NOT NULL
```

**Why Not Caught**:
1. Unit test mocked the query execution completely
2. No integration test ran actual SQL against PostgreSQL
3. SQLite might have different schema (looser typing)

### Pipeline-Status PostgreSQL Error

**File**: `src/cli/commands/pipeline_status.py`

**Bad SQL**:
```sql
WHERE cl.processed_at < datetime('now', '-7 days')  -- ❌ SQLite syntax
```

**Why Not Caught**:
1. Unit tests mock `session.execute()` with fake scalar values
2. Never ran against actual PostgreSQL in CI
3. SQLite syntax works in local dev, fails in production

## Impact Assessment

| Error Type | Production Impact | Detection Time | Fix Time |
|-----------|------------------|----------------|----------|
| Entity extraction SQL | 1,538 articles blocked | Manual log review | Hours |
| Pipeline-status PostgreSQL | Command completely broken | Manual execution | Minutes |
| ML proxy 407 | 1,406 articles blocked | Manual log review | Hours |

**Total Articles Affected**: ~3,000+

**Detection Method**: Manual log inspection (no automated alerts)

## Recommendations

### Immediate (Quick Wins)

1. **Add PostgreSQL Integration Tests to CI** ✅ HIGH PRIORITY
   ```yaml
   # .github/workflows/ci.yml
   integration:
     name: Integration Tests (PostgreSQL)
     runs-on: ubuntu-latest
     services:
       postgres:
         image: postgres:15
         env:
           POSTGRES_PASSWORD: testpass
           POSTGRES_DB: test_db
         options: >-
           --health-cmd pg_isready
           --health-interval 10s
           --health-timeout 5s
           --health-retries 5
     steps:
       - name: Run integration tests
         env:
           DATABASE_URL: postgresql://postgres:testpass@localhost:5432/test_db
         run: pytest -m integration
   ```

2. **Run CI on Feature Branch Pushes**
   ```yaml
   on:
     push:
       branches: [ main, 'feature/**' ]  # Include feature branches
   ```

3. **Add SQL Linting**
   ```bash
   pip install sqlfluff
   sqlfluff lint src/ --dialect postgres
   ```

### Short-Term (This Sprint)

4. **Add Smoke Tests for CLI Commands**
   ```python
   @pytest.mark.integration
   def test_pipeline_status_command_runs(postgres_db):
       """Verify pipeline-status executes without SQL errors."""
       result = subprocess.run(
           ["python", "-m", "src.cli.cli_modular", "pipeline-status"],
           capture_output=True,
           env={"DATABASE_URL": postgres_db}
       )
       assert result.returncode == 0
       assert "ERROR" not in result.stdout
   ```

5. **Require Integration Tests to Pass**
   ```yaml
   # .github/workflows/ci.yml
   deploy:
     needs: [lint, unit, integration]  # Block deploy on integration failure
   ```

6. **Add Pre-Commit Hooks**
   ```yaml
   # .pre-commit-config.yaml
   - repo: https://github.com/sqlfluff/sqlfluff
     rev: 2.3.0
     hooks:
       - id: sqlfluff-lint
         args: [--dialect, postgres]
   ```

### Medium-Term (Next Month)

7. **Migration to SQLAlchemy ORM** (Reduce Raw SQL)
   - Entity extraction query should use ORM joins
   - Type-safe queries catch errors at code time
   - Automatically handles dialect differences

8. **Add Database Schema Validation Tests**
   ```python
   def test_articles_table_has_required_columns(postgres_db):
       """Verify articles table schema matches code expectations."""
       inspector = inspect(postgres_db)
       columns = {c['name'] for c in inspector.get_columns('articles')}
       assert 'id' in columns
       assert 'text' in columns
       assert 'source_id' not in columns  # ❌ This would catch the bug!
   ```

9. **Automated Production Smoke Tests**
   ```bash
   # Run after deployment
   kubectl exec -n production deploy/mizzou-processor -- \
     python -m src.cli.cli_modular pipeline-status
   ```

### Long-Term (Next Quarter)

10. **Full E2E Test Suite**
    - Spin up test Cloud SQL instance in CI
    - Run full pipeline against test data
    - Verify end-to-end data flow

11. **Contract Testing for Database**
    - Use `pytest-postgresql` fixtures
    - Verify schema matches expectations
    - Test migrations against PostgreSQL

12. **Automated Production Monitoring**
    - Alert on SQL errors in logs
    - Track command success rates
    - Dashboards for pipeline health

## Action Items

### Critical (Do Today)
- [ ] Add PostgreSQL service to CI workflow
- [ ] Enable integration tests in CI pipeline
- [ ] Run CI on feature branches

### High Priority (This Week)
- [ ] Add smoke tests for all CLI commands
- [ ] Install and configure sqlfluff
- [ ] Document test requirements for PRs

### Medium Priority (This Month)
- [ ] Refactor raw SQL to SQLAlchemy ORM
- [ ] Add schema validation tests
- [ ] Set up pre-commit hooks

## Test Coverage Goals

| Test Type | Current | Target | Priority |
|-----------|---------|--------|----------|
| Unit (mocked) | ~80% | 85% | Medium |
| Integration (PostgreSQL) | ~0%* | 60% | **HIGH** |
| E2E (full pipeline) | ~5% | 30% | Medium |
| SQL Linting | 0% | 100% | **HIGH** |

*Integration tests exist but aren't run in CI

## Lessons Learned

1. **Mock tests are necessary but insufficient** - They verify logic flow, not correctness
2. **Database dialect matters** - SQLite ≠ PostgreSQL
3. **CI must match production** - Test against the same database as production
4. **SQL strings need validation** - Raw SQL is error-prone
5. **Feature branches need CI** - Errors caught late are expensive

## Conclusion

The root cause is **inadequate integration testing** combined with **SQLite/PostgreSQL dialect mismatch**. Mock-only unit tests provide false confidence. The fix requires running integration tests against PostgreSQL in CI for every commit.

**Estimated effort to fix**: 8-16 hours
**Risk reduction**: 80%+ of SQL errors caught before deployment
**ROI**: Very high - prevents production outages and data pipeline blocks

---

*Created: 2025-10-08*
*Author: GitHub Copilot*
*Issue References: #57 (entity extraction), #56 (pipeline-status)*
