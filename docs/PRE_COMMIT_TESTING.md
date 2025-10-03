# Pre-Commit Testing Guide

This document explains the pre-commit validation system for the MizzouNewsCrawler project.

## Quick Start

Run this before every commit:

```bash
./scripts/pre-commit-checks.sh && git commit -m "your message"
```

## What Gets Tested

### 1. Static Analysis (Ruff) ✅ REQUIRED

**What it does:**
- Checks code style and formatting
- Finds unused imports, undefined variables, syntax errors
- Ensures consistent code formatting

**Status:** ✅ All production code passes

**Manual run:**
```bash
ruff check . --exclude scripts/manual_tests
ruff format .
```

**Auto-fix issues:**
```bash
ruff check --fix .
ruff format .
```

### 2. Type Checking (MyPy) ⚠️ NON-BLOCKING

**What it does:**
- Validates type annotations
- Finds type mismatches and compatibility issues
- Ensures proper typing throughout codebase

**Status:** ⚠️ Shows pre-existing type issues (doesn't block commits)

**Manual run:**
```bash
mypy src/ backend/ --explicit-package-bases --ignore-missing-imports
```

**Skip this check:**
```bash
SKIP_MYPY=1 ./scripts/pre-commit-checks.sh
```

**Why non-blocking?**
The codebase has pre-existing type issues that need to be fixed gradually. We show warnings but don't block commits.

### 3. Unit Tests (Pytest) ✅ REQUIRED

**What it does:**
- Runs full test suite (837 tests)
- Validates code coverage (82.95%)
- Ensures no regressions

**Status:** ✅ 837 tests passing, 2 skipped

**Manual run:**
```bash
pytest tests/ -v
```

**Quick smoke test:**
```bash
pytest tests/ -v -k "not slow" --maxfail=3
```

## Test Results Summary

| Check | Status | Count | Notes |
|-------|--------|-------|-------|
| **Linting** | ✅ Pass | 0 errors | Excludes `scripts/manual_tests/` |
| **Type Checking** | ⚠️ Warning | ~500 issues | Pre-existing, non-blocking |
| **Unit Tests** | ✅ Pass | 837 tests | 82.95% coverage |

## Common Issues

### Issue: Linting Fails

**Problem:** `ruff check` finds errors in your code

**Solution:**
```bash
# Auto-fix most issues
ruff check --fix .
ruff format .

# Check what's left
ruff check .
```

### Issue: Type Checking Fails

**Problem:** MyPy reports type errors

**Solution:**
```bash
# Option 1: Skip mypy (recommended for now)
SKIP_MYPY=1 ./scripts/pre-commit-checks.sh

# Option 2: Fix type issues in your changes
# - Add type hints: def func(x: int) -> str:
# - Import types: from typing import List, Dict
# - Use proper types in function signatures
```

### Issue: Tests Fail

**Problem:** Pytest reports test failures

**Solution:**
```bash
# Run tests with verbose output
pytest tests/ -v --tb=short

# Run specific failing test
pytest tests/path/to/test_file.py::test_name -v

# Fix the code or test, then rerun
pytest tests/ -v
```

### Issue: Tests Take Too Long

**Problem:** Full test suite takes 3+ minutes

**Solution:**
```bash
# Run only fast tests
pytest tests/ -v -k "not slow"

# Stop after first 3 failures
pytest tests/ -v --maxfail=3

# Run specific test directory
pytest tests/cli/ -v
```

## Integration with Git

### Recommended Workflow

```bash
# 1. Make changes
# 2. Run pre-commit checks
./scripts/pre-commit-checks.sh

# 3. If all pass, commit
git add <files>
git commit -m "message"

# 4. Continue development
```

### Git Hook (Optional)

Create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Run pre-commit validation before allowing commit

./scripts/pre-commit-checks.sh

# Exit code determines if commit proceeds
exit $?
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

Now Git will automatically run checks before every commit!

## CI/CD Integration

### Branch Development

- ✅ Pre-commit checks run **locally only**
- ❌ GitHub Actions CI is **disabled** for feature branch
- 🎯 Fast iteration without waiting for CI

### Pull Request

When creating PR to `main`:
- ✅ Full CI runs automatically
- ✅ All 839 tests must pass
- ✅ Coverage must be ≥80%
- ✅ Linting must pass completely
- ⚠️ MyPy warnings reviewed but don't block

## Performance

Typical execution times:

| Check | Time | Can Skip? |
|-------|------|-----------|
| Linting | ~5 seconds | ❌ No |
| Type checking | ~30 seconds | ✅ Yes (SKIP_MYPY=1) |
| Unit tests | ~3 minutes | ❌ No |
| **Total** | **~3.5 minutes** | **~3 min with skip** |

## Maintenance

### Updating the Script

Edit `scripts/pre-commit-checks.sh`:

```bash
# Add new check
echo "🔍 Step 4/4: New Check"
if some_command; then
    echo "✅ New check passed"
else
    echo "❌ New check failed"
    OVERALL_SUCCESS=false
fi
```

### Fixing Type Issues Gradually

To improve type checking over time:

1. Pick a module with few errors
2. Add type hints gradually
3. Run mypy on just that module
4. Repeat for other modules

Example:
```bash
# Check specific module
mypy src/cli/commands/discovery.py --explicit-package-bases --ignore-missing-imports

# Once clean, update pre-commit script to enforce it
```

## Best Practices

### ✅ DO

- Run pre-commit checks before every commit
- Fix linting errors immediately
- Keep tests passing locally
- Skip mypy if it's blocking you (SKIP_MYPY=1)
- Commit frequently with clean tests

### ❌ DON'T

- Commit without running checks
- Push broken tests to the branch
- Ignore linting errors
- Skip all checks (defeats the purpose)
- Commit commented-out test cases

## FAQ

**Q: Do I have to fix all mypy errors?**  
A: No. Mypy is non-blocking. Fix new errors you introduce, but pre-existing issues are okay.

**Q: What if tests fail on something I didn't change?**  
A: Investigate first. If it's a flaky test, report it. If it's a real issue, fix it or get help.

**Q: Can I skip the pre-commit checks?**  
A: Technically yes, but please don't. They catch errors before they reach PR review.

**Q: How do I run just one test?**  
A: `pytest tests/path/to/test_file.py::test_function_name -v`

**Q: The script says "All checks passed" but I see warnings?**  
A: MyPy warnings are expected and non-blocking. As long as linting and tests pass, you're good.

**Q: How do I add test coverage for new code?**  
A: Add tests in `tests/` that exercise your new functions/classes. Use `pytest --cov=src/your_module`.

## Support

For issues with the pre-commit system:

1. Check this document first
2. Review script output carefully
3. Run checks manually to isolate the issue
4. Ask team members if stuck

## Version History

- **2025-10-03**: Initial version
  - Ruff linting with auto-fix
  - MyPy type checking (non-blocking)
  - Pytest with 837 tests
  - ~3.5 minute runtime
