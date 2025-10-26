# Branch Protection & CI/CD Enforcement

## Overview

This repository enforces strict pre-deployment validation through GitHub Actions CI/CD. **All changes must pass validation before merging to main.**

## Required Status Checks

### Pre-Deployment Validation Workflow

Every PR and push must pass the **Pre-Deployment Validation** workflow, which includes:

1. **Origin Proxy Unit Tests**
   - Validates proxy URL rewriting
   - Tests authentication header injection
   - Verifies metadata server bypass logic

2. **Sitecustomize Integration Tests**
   - Validates sitecustomize.py loads without breaking app imports
   - Tests PYTHONPATH configuration
   - Simulates container environment
   - Validates PreparedRequest metadata bypass

3. **Deployment Configuration Validation**
   - PYTHONPATH includes `/app` (prevents ModuleNotFoundError)
   - Image uses placeholder (not `:latest`)
   - CPU limits are reasonable
   - Skaffold configuration is valid
   - Cloud Build uses Skaffold rendering

4. **Full Test Suite**
   - Runs all unit and integration tests
   - Generates coverage reports

## Setting Up Branch Protection

### For Repository Administrators

1. Go to **Settings → Branches** in GitHub
2. Add a branch protection rule for `main`:
   - Branch name pattern: `main`
   - ✅ Require a pull request before merging
   - ✅ Require status checks to pass before merging
     - **Required checks:**
       - `Pre-Deployment Validation`
   - ✅ Require branches to be up to date before merging
   - ✅ Require conversation resolution before merging
   - ✅ Do not allow bypassing the above settings

### Optional but Recommended

- ✅ Require linear history (prevents merge commits)
- ✅ Require deployments to succeed before merging (for production deployments)
- ✅ Require signed commits

## Local Pre-Deployment Validation

Before pushing, run the validation script locally:

```bash
./scripts/pre-deploy-validation.sh processor
```

This catches issues **before** they reach CI/CD, saving time.

## What Gets Blocked

The CI/CD will **block merges** if:

- ❌ Any test fails (unit, integration, or full suite)
- ❌ PYTHONPATH doesn't include `/app` in deployment YAML
- ❌ Deployment uses `image:latest` instead of placeholder
- ❌ Skaffold configuration is invalid
- ❌ Cloud Build doesn't use Skaffold rendering

## Why This Matters

**Real Example:** The PYTHONPATH bug took hours to debug in production because:
- No test validated the deployment configuration
- No test simulated the container environment
- The issue only appeared after multiple deploy cycles

**With these CI/CD checks in place:**
- The PYTHONPATH bug would have been caught in the PR
- No production deployment would have occurred
- Hours of debugging would have been avoided

## For Contributors

### Before Creating a PR

1. Run local validation:
   ```bash
   ./scripts/pre-deploy-validation.sh processor
   ```

2. Ensure all tests pass:
   ```bash
   pytest tests/test_origin_proxy.py -v
   pytest tests/test_sitecustomize_integration.py -v
   ```

3. Check coverage:
   ```bash
   pytest tests/ --cov=src --cov-report=term
   ```

### When CI/CD Fails

1. **Read the failure message** - CI provides detailed output
2. **Run tests locally** - Reproduce the failure
3. **Fix the issue** - Don't try to bypass checks
4. **Push the fix** - CI will re-run automatically

## Troubleshooting CI/CD Failures

### "PYTHONPATH does not include /app"

**Problem:** Deployment YAML has broken PYTHONPATH configuration

**Fix:**
```yaml
# WRONG
env:
- name: PYTHONPATH
  value: "/opt/origin-shim"  # Missing /app!

# CORRECT
env:
- name: PYTHONPATH
  value: "/app:/opt/origin-shim"
```

### "Deployment uses image:latest"

**Problem:** Using `:latest` prevents Cloud Deploy from updating pods

**Fix:**
```yaml
# WRONG
image: us-central1-docker.pkg.dev/.../processor:latest

# CORRECT (placeholder for Skaffold rendering)
image: processor
```

### "Skaffold config missing processor artifact"

**Problem:** Skaffold isn't configured for the service

**Fix:**
```yaml
build:
  artifacts:
    - image: processor
      docker:
        dockerfile: Dockerfile.processor
```

### "Test failures in test_sitecustomize_integration.py"

**Problem:** Changes broke sitecustomize loading or import behavior

**Common causes:**
- Modified `sitecustomize.py` without updating tests
- Changed `origin_proxy.py` API that shim depends on
- PYTHONPATH or import path issues

**Debug:**
```bash
# Run with verbose output
pytest tests/test_sitecustomize_integration.py -vvs

# Run specific test
pytest tests/test_sitecustomize_integration.py::test_sitecustomize_does_not_break_src_imports -vvs
```

## Maintenance

### Adding New Services

When adding a new service (e.g., `api`, `crawler`):

1. Add tests to `tests/test_<service>_integration.py`
2. Add validation to `.github/workflows/pre-deployment-validation.yml`
3. Add validation to `scripts/pre-deploy-validation.sh`
4. Update this documentation

### Updating Test Requirements

If tests need new dependencies:

1. Add to `requirements-dev.txt`
2. Update GitHub Actions workflow to install them
3. Document in PR description

## Emergency Bypass

**Only for production incidents where immediate rollback is needed.**

Repository administrators can bypass checks, but:
- ⚠️  Must be approved by tech lead
- ⚠️  Must have incident ticket
- ⚠️  Must fix properly in follow-up PR

## Questions?

See:
- `COPILOT_INSTRUCTIONS.md` - AI assistance guardrails
- `scripts/pre-deploy-validation.sh` - Local validation script
- `.github/workflows/pre-deployment-validation.yml` - CI/CD workflow
