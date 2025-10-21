# CI vs Local Static Testing Standards Comparison

**Status: ✅ FULLY ALIGNED** (as of 2025-10-20)

## Static Analysis Tools

| Tool | Local (Makefile `lint` target) | CI (`.github/workflows/ci.yml` lint job) | Status |
|------|--------------------------------|------------------------------------------|--------|
| **ruff** | `ruff check .` | `python -m ruff check .` | ✅ **MATCH** |
| **black** | `black --check src/ tests/ web/` | `python -m black --check src/ tests/ web/` | ✅ **MATCH** |
| **isort** | `isort --check-only --profile black src/ tests/ web/` | `python -m isort --check-only --profile black src/ tests/ web/` | ✅ **MATCH** |
| **mypy** | `mypy src/ --ignore-missing-imports` (advisory) | `python -m mypy src/ --ignore-missing-imports` (advisory) | ✅ **MATCH** |
| **flake8** | `flake8 src/ tests/ web/` (advisory, not enforced) | Not included | ⚠️ Optional locally, not in CI |

## Configuration Standards

### Ruff Configuration (`pyproject.toml`)
- **Line length**: 88 (matches black)
- **Target version**: Python 3.11
- **Rules**: E, W, F, I, B, C4, UP
- **Per-file ignores**: Configured for `__init__.py`, tests, alembic, scripts

### Black Configuration (`pyproject.toml`)
- **Line length**: 88
- **Target versions**: Python 3.10, 3.11
- **Exclusions**: `.git`, `.venv`, `venv`, `__pycache__`, `build`, `dist`

### isort Configuration (`pyproject.toml`)
- **Profile**: black (for compatibility)
- **Line length**: 88
- **Multi-line output**: 3
- **Skip gitignore**: true

### mypy Configuration (`pyproject.toml`)
- **Python version**: 3.10
- **ignore_missing_imports**: true
- **disallow_untyped_defs**: false (lenient, incrementally improving)
- **Tests excluded**: `tests.*` modules have `ignore_errors = true`
- **Error codes disabled**: import-untyped, var-annotated, annotation-unchecked, union-attr
- **Special exclusions**: `src/pipeline/crawler.py`

## Test Coverage Standards

| Check | Local (Makefile) | CI (ci.yml) | Notes |
|-------|------------------|-------------|-------|
| **Quick coverage check** | `make coverage`: 45% threshold | N/A | Quick local validation |
| **Full test coverage** | `make test-full`: 70% threshold | Integration job: **80% threshold** | ✅ CI is stricter (good!) |

## Security Tools

| Tool | Local (Makefile `security` target) | CI | Status |
|------|-------------------------------------|-----|--------|
| **bandit** | `bandit -r src/ -ll` | Weekly/manual only (scheduled or workflow_dispatch) | ⚠️ Not on every PR |
| **safety** | `safety check` (advisory) | Weekly/manual only (scheduled or workflow_dispatch) | ⚠️ Not on every PR |

## Advisory vs Enforced Checks

### Enforced (Will Fail CI/Local)
- ✅ ruff check violations
- ✅ black formatting issues
- ✅ isort import ordering issues
- ✅ pytest test failures
- ✅ Coverage below 80% (CI integration job)

### Advisory Only (Warnings, Won't Fail)
- ⚠️ mypy type errors (`continue-on-error: true`)
- ⚠️ flake8 issues (local only, `-flake8` prefix)
- ⚠️ bandit security warnings (CI doesn't fail on issues)
- ⚠️ safety dependency vulnerabilities (CI doesn't fail)

## How to Run Locally

```bash
# Run all lint checks (matches CI lint job)
make lint

# Run security scans (matches CI security job, when run)
make security

# Run type checking
make type-check

# Run full test suite with coverage (matches CI integration job)
make test-full

# Or run all CI checks locally at once
make ci-check
```

## CI Workflow Triggers

- **Lint job**: Runs on every push/PR to `main` or `feature/gcp-kubernetes-deployment`
- **Security job**: Runs weekly (Sundays 3am UTC) or on manual trigger only
- **Integration & Coverage job**: Runs on every push/PR (after lint and unit tests pass)

## Recent Updates

**2025-10-20**: Added mypy type checking to CI lint job
- Matches local `make lint` behavior
- Set to `continue-on-error: true` (advisory only)
- Uses same flags: `--ignore-missing-imports`
- Reads configuration from `pyproject.toml` [tool.mypy] section

## Validation

To verify CI matches local standards, compare:

```bash
# Local lint command
ruff check .
black --check src/ tests/ web/
isort --check-only --profile black src/ tests/ web/
mypy src/ --ignore-missing-imports

# CI lint job (from .github/workflows/ci.yml)
python -m ruff check .
python -m black --check src/ tests/ web/
python -m isort --check-only --profile black src/ tests/ web/
python -m mypy src/ --ignore-missing-imports
```

**Difference**: CI uses `python -m` prefix (explicit module invocation) but this is functionally identical.
