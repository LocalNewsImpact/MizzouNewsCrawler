# Testing Strategy to Match CI

## Problem
Tests pass locally but fail in CI due to environment differences.

## Root Causes
1. **Database differences**: Local uses different DB than CI
2. **Environment variables**: CI sets specific env vars that local doesn't
3. **Test isolation**: Tests not properly marked with pytest markers
4. **Migration state**: CI runs migrations, local might not

## Solutions

### 1. Use the Test Script Before Pushing

**Always run this before pushing:**
```bash
./scripts/test-like-ci.sh
```

This script:
- ✅ Sets PostgreSQL environment variables (matching CI)
- ✅ Runs migrations (like CI does)
- ✅ Runs unit tests (no DB required)
- ✅ Runs PostgreSQL integration tests
- ✅ Fails fast on first error

### 2. Automatic Pre-Push Hook (Installed)

A git pre-push hook is now installed that automatically runs tests before every push.

**To skip the hook** (use sparingly):
```bash
git push --no-verify
```

### 3. Test Marker Requirements

**Follow these rules when writing tests:**

| Test Type | Markers Required | Runs In |
|-----------|-----------------|---------|
| Unit tests (no DB) | None | `integration` job |
| SQLite tests | None | `integration` job |
| PostgreSQL tests | `@pytest.mark.postgres` AND `@pytest.mark.integration` | `postgres-integration` job |
| Backend API tests | `@pytest.mark.postgres` AND `@pytest.mark.integration` | `postgres-integration` job |

**Example:**
```python
import pytest

@pytest.mark.postgres
@pytest.mark.integration
def test_postgres_feature(cloud_sql_session):
    """This test requires PostgreSQL."""
    # Test code using PostgreSQL-specific features
    pass
```

### 4. CI Job Structure

```
┌─────────────────────────────────────────────────┐
│ Unit Tests (no DB)                              │
│ - Fast, no database dependencies                │
│ - Run with: -m "not integration and not postgres"│
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ Integration & Coverage Job                      │
│ - No PostgreSQL service                         │
│ - Run with: -m "not postgres"                   │
│ - SQLite tests + coverage                       │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│ PostgreSQL Integration Job                      │
│ - PostgreSQL 15 service                         │
│ - Run with: -m integration                      │
│ - Migrations run first                          │
│ - Backend + telemetry tests                     │
└─────────────────────────────────────────────────┘
```

### 5. Local PostgreSQL Setup

**Required for local testing:**
```bash
# Install PostgreSQL
brew install postgresql@15  # macOS
sudo apt install postgresql-15  # Ubuntu

# Start PostgreSQL
brew services start postgresql@15  # macOS
sudo systemctl start postgresql  # Ubuntu

# Create test database
createdb news_crawler_test

# Run migrations
alembic upgrade head
```

### 6. Environment Variables

**Set these in your `.env` or shell:**
```bash
export DATABASE_URL="postgresql://yourusername@localhost/news_crawler_test"
export TEST_DATABASE_URL="postgresql://yourusername@localhost/news_crawler_test"
export TELEMETRY_DATABASE_URL="postgresql://yourusername@localhost/news_crawler_test"
```

**Or use the test script** which sets them automatically.

### 7. Debugging Test Failures

**If a test passes locally but fails in CI:**

1. ✅ Run `./scripts/test-like-ci.sh` to reproduce CI environment
2. ✅ Check test markers - does it need `@pytest.mark.postgres`?
3. ✅ Check if test uses `cloud_sql_session` fixture (requires PostgreSQL)
4. ✅ Check if test uses SQLite-specific syntax (shouldn't have postgres marker)
5. ✅ Check environment variables in CI logs
6. ✅ Verify migrations ran in CI before tests

**Common mistakes:**
- ❌ PostgreSQL test missing `@pytest.mark.integration` marker
- ❌ Using tuple parameters `(?, ?)` instead of named params in SQLAlchemy 2.0
- ❌ Missing foreign key IDs in test data
- ❌ Environment variables not set in CI job
- ❌ Forgetting to run migrations before tests

### 8. Quick Reference Commands

```bash
# Run like CI (recommended before every push)
./scripts/test-like-ci.sh

# Run only unit tests (fast)
pytest -m "not integration and not postgres" -v

# Run only PostgreSQL tests (requires local PostgreSQL)
pytest -m integration -v

# Run specific test file
pytest tests/path/to/test_file.py -v

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Skip pre-push hook (use sparingly!)
git push --no-verify
```

### 9. Adding New Tests Checklist

Before committing new tests, verify:

- [ ] Does this test use PostgreSQL? → Add both markers
- [ ] Does this test use `cloud_sql_session`? → Add both markers
- [ ] Does this test use SQLite? → No markers needed
- [ ] Does this test create database records? → Provide ALL required fields
- [ ] Did I run `./scripts/test-like-ci.sh`? → Should pass
- [ ] Are parameters dictionaries not tuples? → SQLAlchemy 2.0 requirement

## Success Metrics

**Before this strategy:**
- ❌ Tests pass locally, fail in CI frequently
- ❌ Multiple push attempts to fix CI
- ❌ Wasted CI minutes
- ❌ Debugging time in CI logs

**After this strategy:**
- ✅ Tests pass locally AND in CI
- ✅ Catch failures before pushing
- ✅ Faster development cycle
- ✅ Consistent test environments
