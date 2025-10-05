# How to Create the Test Infrastructure Fixes GitHub Issue

This directory contains comprehensive documentation for creating a GitHub issue about test failures that need fixing after the Cloud SQL migration.

## Files Created

1. **`ISSUE_TEST_INFRASTRUCTURE_FIXES.md`** (26KB)
   - Comprehensive technical documentation
   - Detailed error analysis and root causes
   - Complete 6-phase implementation roadmap
   - Test coverage plan with specific goals
   - Full success criteria and checklists
   - Use this for technical reference and implementation planning

2. **`GITHUB_ISSUE_CONTENT.md`** (11KB)
   - Concise version formatted for GitHub issues
   - Executive summary of problems
   - Prioritized roadmap (4 phases)
   - Clear success criteria
   - Implementation checklist
   - Use this as the actual GitHub issue body

3. **`create_github_issue.sh`** (executable script)
   - Automated script to create the issue using GitHub CLI
   - Sets appropriate labels and title
   - Use this if you have `gh` CLI configured

## Quick Start: Create the Issue

### Option 1: Using GitHub CLI (Recommended)

If you have GitHub CLI (`gh`) installed and authenticated:

```bash
cd /home/runner/work/MizzouNewsCrawler/MizzouNewsCrawler
./create_github_issue.sh
```

This will automatically create the issue with:
- **Title:** "Test Infrastructure Fixes Required for Cloud SQL Migration"
- **Labels:** bug, testing, database, cloud-sql, priority-high
- **Body:** Contents of `GITHUB_ISSUE_CONTENT.md`

### Option 2: Manual Creation via GitHub Web UI

1. **Navigate to GitHub Issues:**
   - Go to: https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/new

2. **Copy Issue Content:**
   ```bash
   cat GITHUB_ISSUE_CONTENT.md
   ```
   - Copy the entire content of this file
   - Paste it into the GitHub issue description box

3. **Set Issue Title:**
   ```
   Test Infrastructure Fixes Required for Cloud SQL Migration
   ```

4. **Add Labels:**
   - `bug` - These are test failures that need fixing
   - `testing` - Related to test infrastructure
   - `database` - Database migration related
   - `cloud-sql` - Specific to Cloud SQL migration
   - `priority-high` - Blocks confident deployment

5. **Submit the Issue**

### Option 3: Using the GitHub CLI Command Directly

```bash
gh issue create \
  --title "Test Infrastructure Fixes Required for Cloud SQL Migration" \
  --body-file GITHUB_ISSUE_CONTENT.md \
  --label "bug,testing,database,cloud-sql,priority-high" \
  --repo LocalNewsImpact/MizzouNewsCrawler
```

## Issue Summary

The created issue will document:

### Problems (103 test failures/errors)
1. **Cloud SQL Connector Missing** (33 errors) - Missing dependencies in test environment
2. **Alembic Migration Conflicts** (11 failures) - Duplicate table creations
3. **Integration Test Issues** (12 failures) - Database initialization problems
4. **Telemetry Test Mismatches** (5 failures) - Outdated expectations
5. **Missing Constants** (12 failures) - Removed MAIN_DB_PATH references

### Solution Roadmap
- **Phase 1-2** (Critical): Fix environment and Alembic (2 weeks)
- **Phase 3-4** (Important): Fix integration and telemetry tests (2 weeks)
- **Phase 5-6** (Nice-to-have): E2E tests and documentation (2 weeks)

### Expected Outcome
- 0 test failures
- 92% test coverage
- Reliable CI/CD pipeline
- Complete Cloud SQL migration validation

## Next Steps After Creating the Issue

1. **Review with team** - Discuss priorities and timeline
2. **Assign to team members** - Based on expertise (DevOps, Backend, QA)
3. **Create milestone** - "Cloud SQL Migration - Test Fixes"
4. **Link related issues** - Issues #44, #45, #32, #40
5. **Begin Phase 1** - Start with critical fixes (environment + Alembic)

## For More Details

- See `ISSUE_TEST_INFRASTRUCTURE_FIXES.md` for complete technical documentation
- See `docs/coverage-roadmap.md` for existing test coverage information
- See `docs/GCP_KUBERNETES_ROADMAP.md` for overall migration context

## Questions?

If you encounter any issues creating the GitHub issue:
1. Check that you have GitHub CLI installed: `gh --version`
2. Verify authentication: `gh auth status`
3. Check repository access: `gh repo view LocalNewsImpact/MizzouNewsCrawler`
4. If gh CLI issues persist, use Option 2 (Manual Creation)
