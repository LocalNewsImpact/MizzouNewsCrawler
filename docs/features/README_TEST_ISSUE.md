# 📋 Test Infrastructure Fixes - GitHub Issue Documentation

> **Quick Start**: Run `./create_github_issue.sh` to create the GitHub issue automatically.

## What is This?

This directory contains comprehensive documentation for creating a GitHub issue to track test infrastructure fixes needed after the Cloud SQL migration. After the migration, **103 out of 966 tests** are failing or erroring (10.7% failure rate).

## The Problem

```
Current Test Status:
✅ 863 passed (89.3%)
❌ 61 failed (6.3%)
⚠️ 33 errors (3.4%)
⏭️ 9 skipped (0.9%)
───────────────────────
Total: 966 tests
```

### 5 Categories of Failures:

1. **Cloud SQL Connector Missing** (33 errors) 🔴 - Missing `google-cloud-sql-python-connector` in tests
2. **Alembic Migration Conflicts** (11 failures) 🔴 - Duplicate `byline_cleaning_telemetry` table
3. **Integration Test Issues** (12 failures) 🟡 - Can't initialize `DatabaseManager`
4. **Telemetry Expectations Outdated** (5 failures) 🟡 - Old CSV-based schema expectations
5. **Missing Constants** (12 failures) 🟡 - References to removed `MAIN_DB_PATH`

## The Solution

**6-Phase Roadmap** (6 weeks total)

- **Phases 1-2** (Critical, 2 weeks): Fix environment dependencies and Alembic conflicts
- **Phases 3-4** (Important, 2 weeks): Fix integration tests and telemetry expectations  
- **Phases 5-6** (Nice-to-have, 2 weeks): E2E tests and documentation

**Goal**: 0 failures, 92% coverage, reliable CI/CD pipeline

## Documentation Files

### 🎯 Start Here

| File | Purpose | When to Use |
|------|---------|-------------|
| **`README_TEST_ISSUE.md`** | You are here! Quick overview | First read |
| **`TEST_INFRASTRUCTURE_ISSUE_SUMMARY.md`** | Executive summary | For stakeholders/managers |
| **`HOW_TO_CREATE_ISSUE.md`** | Step-by-step guide | When creating the issue |

### 📚 Reference Documentation

| File | Purpose | When to Use |
|------|---------|-------------|
| **`ISSUE_TEST_INFRASTRUCTURE_FIXES.md`** | Complete technical docs (26KB) | During implementation |
| **`GITHUB_ISSUE_CONTENT.md`** | Ready-to-paste issue content (12KB) | When creating issue manually |

### 🔧 Tools

| File | Purpose | When to Use |
|------|---------|-------------|
| **`create_github_issue.sh`** | Automated issue creation | Quick creation via CLI |

## Quick Start: Create the GitHub Issue

### Method 1: Automated (Fastest) ⚡

```bash
./create_github_issue.sh
```

This will:
- ✅ Create issue with proper title
- ✅ Add all relevant labels
- ✅ Set body from GITHUB_ISSUE_CONTENT.md
- ✅ Link to this repository

### Method 2: Manual (Most Flexible) 📝

1. Go to: https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/new
2. Copy contents of `GITHUB_ISSUE_CONTENT.md`
3. Set title: **"Test Infrastructure Fixes Required for Cloud SQL Migration"**
4. Add labels: `bug`, `testing`, `database`, `cloud-sql`, `priority-high`
5. Submit

### Method 3: GitHub CLI Command 💻

```bash
gh issue create \
  --title "Test Infrastructure Fixes Required for Cloud SQL Migration" \
  --body-file GITHUB_ISSUE_CONTENT.md \
  --label "bug,testing,database,cloud-sql,priority-high" \
  --repo LocalNewsImpact/MizzouNewsCrawler
```

## What Happens After Creating the Issue?

1. **Team Review** - Discuss priorities, timeline, and resource allocation
2. **Assignment** - Assign to DevOps (Phase 1-2), Backend (Phase 3-4), QA (Phase 5-6)
3. **Begin Work** - Start with critical fixes in Phase 1
4. **Track Progress** - Use implementation checklists in the issue
5. **Close Issue** - When all 103 failures are resolved

## Estimated Timeline

| Week | Phase | Focus | Target |
|------|-------|-------|--------|
| 1 | 1 | Environment dependencies | <50 failures |
| 2 | 2 | Alembic migration conflicts | <20 failures |
| 3 | 3 | Integration test fixtures | <10 failures |
| 4 | 4 | Telemetry test updates | 0 failures |
| 5 | 5 | E2E test suite | ✅ Coverage |
| 6 | 6 | Documentation + CI/CD | ✅ Complete |

**Target Completion**: March 9, 2025

## Why This Matters

While 89% of tests pass (core functionality works), the failures indicate:

- ❌ Database migration validation incomplete
- ❌ Cloud SQL integration not thoroughly tested
- ❌ CI/CD pipeline reliability at risk
- ❌ Developer workflow disrupted

These issues must be resolved before the Cloud SQL migration can be considered production-ready.

## Need Help?

- **For technical details**: See `ISSUE_TEST_INFRASTRUCTURE_FIXES.md`
- **For creating the issue**: See `HOW_TO_CREATE_ISSUE.md`
- **For executive summary**: See `TEST_INFRASTRUCTURE_ISSUE_SUMMARY.md`
- **For issue content**: See `GITHUB_ISSUE_CONTENT.md`

## Related Issues

- Issue #44: API Backend Cloud SQL Migration (completed)
- Issue #45: Endpoint Migration PR (merged)
- Issue #32: Telemetry System Rollout (completed)
- Issue #40: Database Schema Migration (completed)

## Questions?

Contact the repository maintainers or refer to:
- [Test Coverage Roadmap](docs/coverage-roadmap.md)
- [GCP Kubernetes Roadmap](docs/GCP_KUBERNETES_ROADMAP.md)
- [Cloud SQL Migration Status](CLOUD_SQL_MIGRATION_COMPLETION_SUMMARY.md)

---

**Created**: January 26, 2025  
**Branch**: `copilot/fix-187cd697-9687-4143-a5d6-888e254e4671`  
**Status**: Ready to create GitHub issue
