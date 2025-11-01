# Fast Test Iteration Guide

When you have 1-2 failing tests and need to iterate quickly without waiting 20 minutes for full CI.

## Local Testing (Fastest - Seconds)

### Run specific test file
```bash
make test-file FILE=tests/services/test_classification_service_unit.py
```

### Run tests matching a pattern
```bash
make test-file FILE="tests/test_*.py" ARGS="-k batch"
```

### Run tests by marker
```bash
pytest -m parallel -v --tb=short --no-cov
pytest -m postgres -v --tb=short --no-cov
```

### Run one specific test
```bash
pytest tests/test_parallel_processing_integration.py::test_save_article_entities_autocommit_false_holds_lock -v
```

### Run failing tests only (after a failure)
```bash
pytest --lf -v  # --lf = last failed
```

## CI Testing (Fast - 2-5 minutes)

When you need PostgreSQL or the full CI environment but don't want to wait for the entire suite:

1. Go to **Actions** tab in GitHub
2. Select **"Quick Test"** workflow
3. Click **"Run workflow"**
4. Enter parameters:
   - **Test path**: `tests/services/test_classification_service_unit.py` (or leave blank for all)
   - **Pytest args**: `-k batch -v` (optional filters)
5. Click **"Run workflow"**

### Examples

**Run all tests in a directory:**
- Test path: `tests/services/`
- Pytest args: `-v`

**Run tests matching a name:**
- Test path: `tests/`
- Pytest args: `-k "classification or entity" -v`

**Run only postgres tests:**
- Test path: (blank)
- Pytest args: `-m postgres -v --maxfail=1`

**Re-run your 2 failing tests:**
- Test path: `tests/test_parallel_processing_integration.py`
- Pytest args: `-k "autocommit" -v`

## Full CI (Slow - 20 minutes)

Only run this when:
- You've validated fixes locally or with Quick Test
- Ready to merge (required by branch protection)
- Making changes that could affect many tests

Full CI runs automatically on every PR push.

## Tips

1. **Always test locally first** - catches most issues in seconds
2. **Use Quick Test for integration/postgres tests** - faster than local DB setup
3. **Only push to PR when reasonably confident** - saves CI time
4. **Use `--maxfail=1`** - stop after first failure to get results faster
5. **Skip coverage** - use `--no-cov` for faster runs during iteration
