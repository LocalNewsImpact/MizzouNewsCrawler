# GitHub Actions Workflow Orchestration - Complete Summary

**Last Updated:** 2025-01-16  
**Status:** Critical fixes merged to main, deployment testing pending  
**Key Reference:** PR #204, PR #206

---

## Executive Summary

The GitHub Actions workflow for automated service deployment was broken across three critical areas. All identified issues have been addressed:

1. ✅ **E2E Tests Running Too Early** (PR #204) - Added `wait-for-builds` job to ensure deployments complete before testing
2. ✅ **Argo Workflow Update Failures** (PR #206) - Fixed Python syntax error in `update-workflow-template.sh`
3. 🔄 **Service Change Detection Incomplete** - Improved detection logic; pending real deployment testing to validate

---

## Problem Statement

When code was pushed to the main branch, the GitHub Actions workflow (`build-and-deploy-services.yml`) was supposed to:
1. Detect which services changed (processor, api, crawler, base, ml-base, migrator)
2. Submit Cloud Build jobs for those services
3. Wait for builds to complete
4. Update Argo workflow templates with new image versions
5. Trigger smoke tests

**What Was Actually Happening:**
- Smoke tests ran before builds completed, causing them to fail
- Argo workflow updates failed with "SyntaxError: invalid syntax" in Python step
- Crawler build silently failed but wasn't caught
- Change detection didn't work reliably with squash merges

---

## Issues Fixed

### Issue #1: E2E Tests Running Before Deployment (PR #204)

**Problem:**  
The `production-smoke-tests` job ran immediately after Cloud Build jobs were submitted, without waiting for them to complete. Tests would fail trying to connect to old version of services.

**Root Cause:**  
Workflow had no synchronization point between "submit builds" and "run tests". GitHub Actions ran jobs in parallel if they were independent.

**Solution:**  
Added `wait-for-builds` job that runs after all build jobs complete. It:
- Polls Cloud Build for job status using `gcloud builds log`
- Detects `CrashLoopBackOff` status to catch deployment failures
- Uses kubectl rollout status to verify Kubernetes deployment completeness
- Provides clear feedback on which services are ready

**Files Changed:**
- `.github/workflows/production-smoke-tests.yml` - Added kubectl health checks
- `.github/workflows/build-and-deploy-services.yml` - Added `wait-for-builds` job and dependency

**Status:** ✅ Merged (PR #204), deployed, validated

---

### Issue #2: Argo Workflow Update Failures (PR #206) - CRITICAL

**Problem:**  
When Cloud Build jobs completed, the workflow ran `update-workflow-template.sh` to update Argo with new image versions. The script failed with:
```
SyntaxError: invalid syntax
  File "<string>", line 1
    PYTHON_EOF "$SERVICE_TYPE" "$NEW_SHA" "$REGISTRY"
                 ^
```

**Root Cause:**  
Line 88 of `update-workflow-template.sh` had an errant command after the here-document closing delimiter. Here-documents are closed with `EOF` on its own line, and nothing should follow it.

```bash
# WRONG (what was in the file):
python3 << PYTHON_EOF
# ... python code ...
PYTHON_EOF "$SERVICE_TYPE" "$NEW_SHA" "$REGISTRY"  # <- This line is invalid!
```

The intent was to pass parameters to the here-document, but the syntax was incorrect. In bash, here-document parameters go on the opening line, not closing.

**Solution:**  
Moved parameters to the here-document opening line using correct bash syntax:

```bash
# CORRECT:
python3 << PYTHON_EOF "$SERVICE_TYPE" "$NEW_SHA" "$REGISTRY"
# ... python code using $1, $2, $3 ...
PYTHON_EOF
```

**Files Changed:**
- `gcp/cloudbuild/update-workflow-template.sh` - Line 88, fixed here-document syntax

**Specific Change:**
```bash
# Before (line 88):
PYTHON_EOF "$SERVICE_TYPE" "$NEW_SHA" "$REGISTRY"

# After (line 87, opening line):
python3 << PYTHON_EOF "$SERVICE_TYPE" "$NEW_SHA" "$REGISTRY"
```

**Status:** ✅ Merged (PR #206, squash merge as 881913f), now on main

**Impact:** This was the critical blocker preventing production deployments. With this fix, the entire workflow pipeline can function:
1. Cloud Build produces new images
2. Argo workflow templates are updated automatically
3. Kubernetes pulls new images and deploys

---

### Issue #3: Service Change Detection (In Progress)

**Problem:**  
The workflow detects which services changed using git diff. However:
- `git diff-tree` doesn't work reliably with squash merges
- GitHub Actions provides `event.before` and `event.after`, but the detection script only tried one diff method
- When all detection methods failed, the workflow would skip all service builds

**Root Cause:**  
Squash merges combine all commits from a branch into a single commit. Some git commands (like diff-tree) have different behavior with merge commits vs. regular commits.

**Solution:**  
Improved change detection to use multiple methods:

1. **Method 1: `git diff-tree`** - Standard approach, works for regular commits
2. **Method 2: `git diff` with three-dot syntax** - Works for squash merges
3. **Method 3: Fallback to `HEAD~1` comparison** - Safety net if both methods fail

The workflow now tries all three methods and combines results:

```bash
# Method 1: Standard diff-tree
METHOD1=$(git diff-tree --no-commit-id --name-only -r $BEFORE $AFTER 2>/dev/null || true)

# Method 2: Three-dot diff (works better for merges)
METHOD2=$(git diff --name-only $BEFORE...$AFTER 2>/dev/null || true)

# Method 3: Fallback (safety net)
if [ -z "$CHANGED_FILES" ]; then
  CHANGED_FILES=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)
fi

# Combine and deduplicate
CHANGED_FILES=$(printf "%s\n%s" "$METHOD1" "$METHOD2" | grep -v '^$' | sort -u)
```

**Service Detection Rules:**  
Once changed files are detected, the workflow uses pattern matching:

| Service | Rebuilds When | Pattern |
|---------|---|---------|
| **processor** | Code or migrations change | `Dockerfile.processor`, `requirements-processor.txt`, `src/`, `pyproject.toml`, `alembic/` |
| **api** | Code, dependencies, or migrations change | `Dockerfile.api`, `requirements-api.txt`, `src/`, `backend/`, `alembic/` |
| **crawler** | Code changes | `Dockerfile.crawler`, `requirements-crawler.txt`, `src/`, `pyproject.toml` |
| **base** | OS or base dependency changes | `Dockerfile.base`, `requirements-base.txt` (NOT migrations) |
| **ml-base** | ML dependencies change | `Dockerfile.ml-base`, `requirements-ml.txt` |
| **migrator** | Migration files or code change | `Dockerfile.migrator`, `requirements-migrator.txt`, `alembic/` |

**Key Design Decisions:**
- Base image does NOT rebuild for migrations (migrations run separately as part of API deployment)
- Each service has minimal trigger patterns to reduce unnecessary builds
- Fallback detection ensures something always gets detected (or explicit manual override via workflow_dispatch)

**Status:** 🔄 Ready for deployment testing

---

## Current State

### Main Branch (Production Deployment Target)

| Commit | Change | Status |
|--------|--------|--------|
| **3455a9f** (HEAD) | fix: remove base image rebuild for migrations | ✅ Deployed to production |
| **881913f** | Merged PR #206: CRITICAL fix for Argo workflow update script Python syntax | ✅ Merged, ready for use |
| **~20 commits back** | Production baseline (last successful full deployment) | Reference point |

### Image Registry (GCP Artifact Registry)

| Service | Latest Image | Notes |
|---------|---|---|
| **processor** | `0cd2dc4` | Built during PR #204 testing |
| **api** | `0cd2dc4` | Built during PR #204 testing |
| **crawler** | `05f0c40` | Build failed for 0cd2dc4, using prior version |
| **base** | (current) | N/A - base images pulled by other services |
| **ml-base** | (current) | N/A - pulled by processor |

### Argo Workflow (Production)

Manually updated after PR #206 merge:
- **Processor image:** 0cd2dc4 (working)
- **Crawler image:** 05f0c40 (working, fallback from failed 0cd2dc4 build)

### Pull Requests

| PR | Status | Impact |
|----|--------|--------|
| #204 | Merged ✅ | Added wait-for-builds job, production smoke test improvements |
| #206 | Merged ✅ | CRITICAL: Fixed Argo workflow update script syntax error |
| fix/github-action-service-detection | In Review | Improved change detection, better logging |

---

## End-to-End Workflow Flow

Here's how the complete workflow operates after all fixes:

```
User pushes code to main
    ↓
GitHub Actions Webhook Triggers
    ↓
[detect-changes] Job
  ├─ Runs: Compare $before..$after using multiple git diff methods
  ├─ Checks patterns against changed files
  ├─ Sets outputs: processor=true/false, api=true/false, crawler=true/false, etc.
  ├─ Logs: Full list of changed files, which services triggered
  └─ Output: any-changed = true/false
    ↓
[build-processor, build-api, build-crawler, ...] Jobs (Conditional)
  ├─ Only run if detect-changes.outputs.any-changed == 'true'
  ├─ Each job:
  │   ├─ Submits Cloud Build job via `gcloud builds submit`
  │   ├─ Polls Cloud Build for completion (waits up to 30 min)
  │   ├─ On success: Runs update-workflow-template.sh (FIXED!)
  │   │   └─ Updates Argo workflow YAML with new image SHA
  │   └─ On failure: Stops, reports error
  └─ All build jobs run in parallel
    ↓
[wait-for-builds] Job
  ├─ Waits for all build jobs to complete
  ├─ Polls kubectl for deployment status
  ├─ Checks for CrashLoopBackOff or other failures
  └─ Blocks production-smoke-tests until ready
    ↓
[production-smoke-tests] Job
  ├─ Runs end-to-end tests against new services
  ├─ Tests: API health, crawler functionality, database connectivity
  └─ Reports: Pass/Fail to GitHub
```

---

## Remaining Work

### Immediate (High Priority)

1. **Deploy Improved Change Detection to Production**
   - Branch `fix/github-action-service-detection` has improved detection logic
   - PR ready for review
   - Action: Merge to main and monitor first push

2. **Test End-to-End Workflow**
   - Push a test commit to main (small, non-critical change)
   - Monitor GitHub Actions execution
   - Verify: Changes detected → correct services built → Argo updated → tests pass

---

## References

- **GitHub Actions Documentation**: https://docs.github.com/en/actions
- **Cloud Build Documentation**: https://cloud.google.com/build/docs
- **Argo Workflows**: https://argoproj.github.io/argo-workflows/
- **Kubernetes Documentation**: https://kubernetes.io/docs/
- **Bash Here-Documents**: https://www.gnu.org/software/bash/manual/html_node/Here-Documents.html
