# Static Analysis & Code Quality Tools

This document outlines the static analysis tools configured for this project, both for CI and local development.

## 🚀 Quick Start

### Run All Checks Locally
```bash
# Install pre-commit (one-time setup)
pip install pre-commit
pre-commit install

# Run all checks manually
pre-commit run --all-files

# Or run individual tools:
make lint      # Run all linting
make format    # Auto-format code
make security  # Security scan
```

## 🔧 Configured Tools

### 1. **Ruff** - Fast Python Linter
- **What**: Modern, fast Python linter (replacement for flake8, pycodestyle, isort, etc.)
- **Status**: ✅ **CI Enforced** (must pass)
- **Config**: `pyproject.toml` → `[tool.ruff]`
- **Run**: `ruff check .`
- **Fix**: `ruff check --fix .`
- **Coverage**: E, W, F, I, B, C4, UP rules

### 2. **Black** - Code Formatter
- **What**: Opinionated Python code formatter
- **Status**: ✅ **CI Enforced** (must pass)
- **Config**: `pyproject.toml` → `[tool.black]`
- **Check**: `black --check src/ tests/ web/`
- **Fix**: `black src/ tests/ web/`
- **Line Length**: 88 characters (modern standard)

### 3. **isort** - Import Sorter
- **What**: Sorts and organizes Python imports
- **Status**: ✅ **CI Enforced** (must pass)
- **Config**: `pyproject.toml` → `[tool.isort]` (Black-compatible profile)
- **Check**: `isort --check-only --profile black src/ tests/ web/`
- **Fix**: `isort --profile black src/ tests/ web/`

### 4. **Bandit** - Security Scanner
- **What**: Finds common security issues in Python code
- **Status**: ⚠️ **CI Advisory** (runs but doesn't fail build)
- **Config**: `pyproject.toml` → `[tool.bandit]`
- **Run**: `bandit -r src/ -ll`
- **Current Issues**: 1 HIGH, 19 MEDIUM, 84 LOW (mostly false positives)
- **Recommendation**: Review HIGH/MEDIUM issues periodically

### 5. **Safety** - Dependency Vulnerability Scanner
- **What**: Checks dependencies for known security vulnerabilities
- **Status**: ⚠️ **CI Advisory** (runs but doesn't fail build)
- **Run**: `safety check`
- **Recommendation**: Review before production deployments

### 6. **mypy** - Static Type Checker
- **What**: Optional static type checking for Python
- **Status**: 🔧 **Local Development** (not in CI yet)
- **Config**: `pyproject.toml` → `[tool.mypy]`
- **Run**: `mypy src/`
- **Current State**: ~100+ type errors (gradual adoption recommended)
- **Note**: Configured leniently to avoid blocking development

### 7. **flake8** - Classic Linter
- **What**: Traditional Python linter (largely replaced by Ruff)
- **Status**: 🔧 **Local Development Only**
- **Config**: `.flake8`
- **Run**: `flake8 src/ tests/ web/`
- **Note**: 90 violations remaining, not enforced in CI

### 8. **pytest** - Testing Framework
- **What**: Test runner with coverage reporting
- **Status**: ✅ **CI Enforced** (must pass with 70% coverage)
- **Config**: `pyproject.toml` → `[tool.pytest.ini_options]`
- **Run**: `pytest --cov=src --cov-report=term-missing`
- **Current**: 837 tests passing, 82.98% coverage

## 📋 CI Pipeline

### What Runs Automatically

#### On Every PR/Push to `main`:
1. **Lint Job** (Python 3.10, 3.11):
   - ✅ Ruff code quality checks (BLOCKS merge if fails)
   - ✅ Black format verification (BLOCKS merge if fails)
   - ✅ isort import ordering (BLOCKS merge if fails)

2. **Security Job**:
   - ⚠️ Bandit security scan (advisory only)
   - ⚠️ Safety dependency check (advisory only)

3. **Test Job** (Python 3.10, 3.11):
   - ✅ Full test suite with coverage (BLOCKS merge if <70% coverage)
   - 📊 Uploads coverage reports as artifacts

#### Weekly (Sundays 3 AM UTC):
4. **Stress Test Job**:
   - 🔥 Concurrent stress tests
   - Only runs on schedule or manual dispatch

### What Will Block Your PR

Your PR will **FAIL CI** if:
- ❌ Ruff finds any errors (E721, F401, etc.)
- ❌ Code is not Black-formatted
- ❌ Imports are not sorted (isort)
- ❌ Any test fails
- ❌ Coverage drops below 70%

Security scans (bandit, safety) will NOT block PRs but should be reviewed.

## 🛠️ Makefile Commands

Add these to your `Makefile` for easy access:

```makefile
.PHONY: lint format security type-check test-full

lint:
	ruff check .
	black --check src/ tests/ web/
	isort --check-only --profile black src/ tests/ web/
	flake8 src/ tests/ web/ || true

format:
	black src/ tests/ web/
	isort --profile black src/ tests/ web/
	ruff check --fix .

security:
	bandit -r src/ -ll
	safety check || true

type-check:
	mypy src/ --ignore-missing-imports

test-full:
	pytest --cov=src --cov-report=html --cov-report=term-missing --cov-fail-under=70
```

## 📝 Configuration Summary

| Tool | Config File | Line Length | Python Version |
|------|-------------|-------------|----------------|
| Ruff | `pyproject.toml` | 88 | 3.10+ |
| Black | `pyproject.toml` | 88 | 3.10, 3.11 |
| isort | `pyproject.toml` | 88 | - |
| flake8 | `.flake8` | 88 | - |
| mypy | `pyproject.toml` | - | 3.10 |
| Bandit | `pyproject.toml` | - | - |
| pytest | `pyproject.toml` | - | 3.10, 3.11 |

## 🎯 Recommended Workflow

### Before Committing:
```bash
# Auto-fix what can be fixed
make format

# Check for remaining issues
make lint

# Run tests
pytest

# (Optional) Run full pre-commit suite
pre-commit run --all-files
```

### Before Creating PR:
```bash
# Full test suite with coverage
make test-full

# Security check
make security

# Ensure CI will pass
ruff check . && black --check src/ tests/ web/ && isort --check-only --profile black src/ tests/ web/
```

## 📊 Current Status

As of October 2, 2025:

| Check | Status | Count |
|-------|--------|-------|
| ✅ Ruff | PASSING | 0 errors |
| ✅ Black | PASSING | All files formatted |
| ✅ isort | PASSING | All imports sorted |
| ⚠️ Bandit | 104 issues | 1 HIGH, 19 MED, 84 LOW |
| ⚠️ flake8 | 90 violations | (not in CI) |
| ⚠️ mypy | ~100+ errors | (not in CI) |
| ✅ pytest | 837 tests | 82.98% coverage |

## 🔮 Future Improvements

### Short Term:
- [ ] Review and fix Bandit HIGH severity issue
- [ ] Add mypy to CI with lenient config (track but don't block)
- [ ] Reduce flake8 violations to <50

### Medium Term:
- [ ] Enable stricter Ruff rules (D - docstrings, N - naming)
- [ ] Increase test coverage to 85%
- [ ] Add mutation testing with mutmut

### Long Term:
- [ ] Full mypy strict mode
- [ ] 100% type coverage
- [ ] Zero security issues

## 📚 References

- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [Black Documentation](https://black.readthedocs.io/)
- [isort Documentation](https://pycqa.github.io/isort/)
- [Bandit Documentation](https://bandit.readthedocs.io/)
- [mypy Documentation](https://mypy.readthedocs.io/)
- [pre-commit Documentation](https://pre-commit.com/)
