# Feature Branch: GCP/Kubernetes Deployment

**Branch Name**: `feature/gcp-kubernetes-deployment`

**Status**: 🚧 In Development

**Purpose**: Implement complete GCP/Kubernetes deployment infrastructure for MizzouNewsCrawler.

---

## Branch Development Guidelines

### CI/CD Policy

**⚠️ CI is DISABLED for this branch during development**

- GitHub Actions CI will **NOT run** on commits to this branch
- CI is configured to only run on:
  - Pushes to `main`
  - Pull requests targeting `main`
- We will enable full CI testing during PR review before merging

**Why?**
- Rapid iteration without waiting for CI (20+ minute runs)
- Avoid unnecessary GitHub Actions minutes
- Focus on functionality first, testing second
- Full CI will run when PR is created

### Commit Strategy

**Local commits only** until ready for review:

```bash
# Commit locally
git add <files>
git commit -m "message"

# DO NOT push until phase complete or need backup
# git push  # ❌ Avoid during active development
```

**When to push:**
- ✅ Major phase milestone complete (want backup)
- ✅ Need to share work with others
- ✅ End of work session (optional backup)
- ✅ Ready for PR and code review

### Development Workflow

1. **Work locally**: Make changes, commit frequently
2. **Test locally**: **REQUIRED before every commit**
3. **Push milestone**: When phase complete or need backup
4. **Create PR**: Only when fully ready for review and merge
5. **CI runs**: Full testing happens during PR review

### ✅ Required Tests Before Every Commit

**Run these commands before `git commit`:**

```bash
# 1. Static analysis (linting)
make lint
# or individually:
ruff check .
ruff format --check .

# 2. Type checking
mypy src/ backend/ --ignore-missing-imports

# 3. Unit tests
pytest tests/ -v

# 4. Quick smoke test (optional but recommended)
pytest tests/ -v -k "not slow" --maxfail=3
```

**Why test locally?**
- ✅ Catch errors immediately, not in PR review
- ✅ Maintain code quality throughout development
- ✅ Faster feedback loop than waiting for CI
- ✅ Ensure tests pass before creating commits
- ✅ Avoid "fix tests" commits cluttering history

**Quick validation script:**

```bash
# Create this as scripts/pre-commit-checks.sh
#!/bin/bash
set -e

echo "🔍 Running static analysis..."
make lint

echo "🔍 Running type checks..."
mypy src/ backend/ --ignore-missing-imports

echo "🧪 Running tests..."
pytest tests/ -v

echo "✅ All checks passed! Safe to commit."
```

Make it executable: `chmod +x scripts/pre-commit-checks.sh`

Then before committing: `./scripts/pre-commit-checks.sh && git commit -m "message"`

---

## Implementation Phases

### ✅ Phase 1: Containerization (COMPLETE)
- [x] Dockerfile.api
- [x] Dockerfile.crawler
- [x] Dockerfile.processor
- [x] docker-compose.yml
- [x] .dockerignore
- [x] docs/DOCKER_GUIDE.md

**Commits**: 1
**Status**: Ready for local testing

### 🔄 Phase 2: GCP Infrastructure (IN PROGRESS)
- [ ] GCP project setup
- [ ] GKE cluster configuration
- [ ] Cloud SQL instance
- [ ] Cloud Storage buckets
- [ ] BigQuery dataset
- [ ] Terraform/gcloud scripts

**Commits**: 0
**Status**: Not started

### ⏳ Phase 3: Kubernetes Configuration (PENDING)
- [ ] Helm chart structure
- [ ] Deployment manifests
- [ ] ConfigMaps and Secrets
- [ ] HPA configurations
- [ ] Ingress setup

### ⏳ Phase 4: CI/CD Pipeline (PENDING)
- [ ] GitHub Actions workflows
- [ ] Workload Identity Federation
- [ ] Cloud Build integration
- [ ] Deployment automation

### ⏳ Phase 5: Data Migration (PENDING)
- [ ] SQLite → Cloud SQL migration
- [ ] BigQuery export pipeline
- [ ] Cloud Storage integration

### ⏳ Phase 6: Frontend Development (PENDING)
- [ ] React application scaffolding
- [ ] Admin portal
- [ ] Telemetry dashboard

### ⏳ Phase 7: Security & Compliance (PENDING)
- [ ] OAuth 2.0 implementation
- [ ] RBAC system
- [ ] Secrets management

### ⏳ Phase 8: Observability & Monitoring (PENDING)
- [ ] Cloud Monitoring dashboards
- [ ] Alert policies
- [ ] Structured logging

### ⏳ Phase 9: Testing & Validation (PENDING)
- [ ] Integration tests
- [ ] Load testing
- [ ] Staging environment

### ⏳ Phase 10: Production Launch (PENDING)
- [ ] Production deployment
- [ ] Cost optimization
- [ ] Documentation

---

## Local Testing Commands

### Quick Pre-Commit Validation

**Use the automated script (RECOMMENDED):**

```bash
# Run all checks before committing
./scripts/pre-commit-checks.sh

# If all pass, commit
git add <files>
git commit -m "message"
```

This script runs:
1. Static analysis (ruff)
2. Type checking (mypy)
3. Unit tests (pytest)

### Test Docker Images

```bash
# Build all images
docker compose build

# Test API
docker compose up -d
curl http://localhost:8000/health

# Test crawler
docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 1

# Test processor
docker compose run --rm processor python -m src.cli.main extract --limit 5

# Clean up
docker compose down -v
```

### Manual Tests (No CI)

Since CI is disabled, run these manually before pushing:

```bash
# Linting
ruff check src/ backend/ tests/
black --check src/ backend/ tests/
mypy src/ backend/

# Unit tests
pytest tests/ --cov --cov-report=term-missing

# Security scan (if needed)
bandit -r src/ backend/
safety check --json
```

---

## GitHub Issues

- #15: Phase 1 - Containerization ✅
- #16: Phase 2 - GCP Infrastructure ⏳
- #17: Phase 3 - Kubernetes Configuration ⏳
- #18: Phase 4 - CI/CD Pipeline ⏳
- #19: Phase 5 - Data Migration ⏳
- #20: Phase 6 - Frontend Development ⏳
- #21: Phase 7 - Security & Compliance ⏳
- #22: Phase 8 - Observability & Monitoring ⏳
- #23: Phase 9 - Testing & Validation ⏳
- #24: Phase 10 - Production Launch ⏳

---

## Review Checklist (Before PR)

Before creating a pull request, ensure:

- [ ] All phase deliverables complete
- [ ] Local Docker tests passing
- [ ] Manual linting/formatting applied
- [ ] Documentation updated
- [ ] No secrets or credentials committed
- [ ] .gitignore properly configured
- [ ] Branch rebased on latest main
- [ ] Commit messages are clear
- [ ] Ready for full CI test suite

**Then**:
1. Push branch to remote
2. Create pull request
3. CI will run automatically
4. Address any CI failures
5. Request code review
6. Merge when approved

---

## Notes

- **Budget conscious**: Minimize cloud resource usage during development
- **Iterative approach**: Deploy phases incrementally
- **Test locally first**: Reduce cloud costs and iteration time
- **Document as you go**: Update this file with progress

---

Last Updated: October 2, 2025
Current Phase: Phase 1 Complete, Phase 2 Planning
