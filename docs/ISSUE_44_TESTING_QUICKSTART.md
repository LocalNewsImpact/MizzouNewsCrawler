# Quick Start Guide - Issue #44 Testing

**Quick reference for running Issue #44 tests**

## Prerequisites

```bash
# Activate virtual environment
source venv/bin/activate

# Verify pytest installed
pytest --version
```

## Run Unit Tests (Local - Fast)

These tests use in-memory SQLite and don't require Cloud SQL:

```bash
# Run all backend tests
pytest tests/backend/ -v

# Run specific endpoint tests
pytest tests/backend/test_ui_overview_endpoint.py -v
pytest tests/backend/test_articles_endpoint.py -v
pytest tests/backend/test_options_endpoints.py -v

# Run with coverage
pytest tests/backend/ --cov=backend/app --cov-report=term-missing

# Skip coverage enforcement (during development)
pytest tests/backend/ -v --no-cov
```

**Expected**: 44 tests, ~2-5 seconds

## Run Integration Tests (Cloud SQL - Slower)

These tests require Cloud SQL test instance:

```bash
# Set environment variables
export TEST_DATABASE_URL="postgresql://user:pass@/test_db?host=/cloudsql/instance"
export CLOUD_SQL_INSTANCE="mizzou-news-crawler:us-central1:mizzou-db-test"
export USE_CLOUD_SQL_CONNECTOR="true"

# Run integration tests
pytest tests/integration/ -v -m integration
```

**Expected**: 22 tests, ~10-30 seconds

**Skip if not configured**: Tests auto-skip if `TEST_DATABASE_URL` not set

## Run All Tests

```bash
# Unit tests only (default)
pytest tests/backend/ -v

# Unit + integration
pytest tests/backend/ tests/integration/ -v
```

## Test Results

### All Passing ✅

```text
tests/backend/test_ui_overview_endpoint.py::test_ui_overview_empty_database PASSED
tests/backend/test_ui_overview_endpoint.py::test_ui_overview_with_articles PASSED
...
======= 44 passed in 3.21s =======
```

### Some Failing ❌

Check:

1. **Import errors**: Verify `backend/app/main.py` has correct imports
2. **Database errors**: Check fixtures in `tests/backend/conftest.py`
3. **Endpoint not implemented**: Endpoint migration not complete yet

## Common Issues

### Issue: "Module not found"

```bash
# Add project root to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Issue: "Coverage threshold not met"

```bash
# Skip coverage during test development
pytest tests/backend/ -v --no-cov
```

### Issue: "TEST_DATABASE_URL not set"

```bash
# Integration tests will be skipped (expected)
# Or set up Cloud SQL connection:
export TEST_DATABASE_URL="postgresql://..."
```

## Next Steps

After tests pass:

1. **Implement migrations** in `backend/app/main.py`
2. **Run tests again** to verify correctness
3. **Check coverage**: `pytest tests/backend/ --cov=backend/app`
4. **Deploy to staging**
5. **Run integration tests** against staging

## Documentation

- Full testing plan: `docs/ISSUE_44_TESTING_PLAN.md`
- Infrastructure summary: `docs/ISSUE_44_TESTING_INFRASTRUCTURE.md`
- Issue #44: https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/44
