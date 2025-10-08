# GitHub CI Configuration Update: Smoke Tests Only on Main Branch

## Changes Made

### 1. Updated `smoke-proxy-tests.yml`
**Before:**
```yaml
on:
  pull_request:
    branches: [feature/gcp-kubernetes-deployment, main]
  workflow_dispatch: {}
```

**After:**
```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch: {}
```

**Impact:** 
- Smoke proxy tests now only run on pushes to `main` branch or PRs targeting `main`
- Will NOT run on feature branches like `feature/gcp-kubernetes-deployment`
- Still allows manual triggering via `workflow_dispatch`

### 2. Updated `ci.yml` - Added Explicit Conditions

#### origin-proxy-only Job
**Before:**
```yaml
origin-proxy-only:
  name: Origin-proxy tests
  runs-on: ubuntu-latest
  needs: [unit]
```

**After:**
```yaml
origin-proxy-only:
  name: Origin-proxy tests (smoke)
  runs-on: ubuntu-latest
  needs: [unit]
  # Only run smoke tests on main branch or PRs to main
  if: github.event_name == 'push' || github.base_ref == 'main' || github.ref == 'refs/heads/main'
```

#### integration Job
**Before:**
```yaml
integration:
  name: Integration & Coverage
  runs-on: ubuntu-latest
  needs: [unit]
```

**After:**
```yaml
integration:
  name: Integration & Coverage
  runs-on: ubuntu-latest
  needs: [unit]
  # Only run full integration tests on main branch or PRs to main
  if: github.event_name == 'push' || github.base_ref == 'main' || github.ref == 'refs/heads/main'
```

**Impact:**
- Both smoke and integration tests have explicit conditions
- Will NOT run on branches that aren't targeting `main`
- Reduces CI time for feature branch work

## What Still Runs on Feature Branches

Even on feature branches (when not targeting `main`), these jobs will still run:
- ✅ **lint** - Code quality checks (ruff, black, isort)
- ✅ **unit** - Fast unit tests (excluding integration/e2e/slow tests)

## What Only Runs on Main-Related Branches

These heavier jobs only run on `main` or PRs to `main`:
- 🔒 **origin-proxy-only** - Smoke tests for proxy adapter
- 🔒 **integration** - Full test suite with coverage requirements
- 🔒 **security** - Security scans (scheduled/manual only)
- 🔒 **stress** - Stress tests (scheduled/manual only)

## Rationale

1. **Faster Feedback**: Feature branch development gets faster CI feedback (lint + unit tests only)
2. **Resource Efficiency**: Expensive integration/e2e tests only run when necessary
3. **Main Branch Protection**: Full test suite still runs on all PRs targeting `main`
4. **Manual Override**: All workflows can still be triggered manually via `workflow_dispatch`

## Testing the Changes

### To verify on a feature branch:
```bash
# Push to feature branch
git push origin feature/my-branch

# Expected: Only lint and unit tests run
# NOT running: smoke tests, integration tests, e2e tests
```

### To verify on main:
```bash
# Create PR to main
gh pr create --base main

# Expected: All jobs run (lint, unit, smoke, integration)
```

## Workflow Trigger Summary

| Workflow | Push to Main | PR to Main | Push to Feature | PR to Feature | Manual |
|----------|--------------|------------|-----------------|---------------|---------|
| lint | ✅ | ✅ | ✅ | ✅ | ✅ |
| unit | ✅ | ✅ | ✅ | ✅ | ✅ |
| origin-proxy-only | ✅ | ✅ | ❌ | ❌ | ✅ |
| integration | ✅ | ✅ | ❌ | ❌ | ✅ |
| smoke-proxy-tests.yml | ✅ | ✅ | ❌ | ❌ | ✅ |
| security | ⏰ Scheduled | ⏰ Scheduled | ❌ | ❌ | ✅ |
| stress | ⏰ Scheduled | ⏰ Scheduled | ❌ | ❌ | ✅ |

⏰ = Only runs on schedule (weekly) or manual trigger

## Files Modified
- `.github/workflows/smoke-proxy-tests.yml`
- `.github/workflows/ci.yml`
